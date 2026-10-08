from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.utils import timezone

from .models import UserRewardProfile, RewardPointTransaction
from .serializers import RewardPointTransactionSerializer
from .services import get_tier_info, process_expired_points, award_points


class StandardRewardsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'success': True,
            'message': 'Points history retrieved successfully.',
            'total': self.page.paginator.count,
            'data': data
        })


@extend_schema(
    tags=["Rewards & Gamification"],
    summary="Rewards Summary & Tier Progress",
    description="Retrieve available points balance, lifetime points, current tier (Bronze-Diamond), progress to next tier, and 24-month validity details.",
    responses={
        200: OpenApiResponse(description="Rewards balance and tier details retrieved"),
    }
)
class RewardPointsSummaryView(APIView):
    """
    API endpoint to retrieve current user's available points, lifetime points,
    current tier, next tier requirements, and 24-month validity details.
    
    GET /api/rewards/points/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        # 1. Fetch profile once
        profile, _ = UserRewardProfile.objects.get_or_create(user=request.user)

        # 2. Process any expired points only if unexpired expired records exist (SR-24)
        has_expired = RewardPointTransaction.objects.filter(
            user=request.user,
            is_expired=False,
            expires_at__lte=timezone.now(),
            points__gt=0
        ).exists()
        if has_expired:
            process_expired_points(request.user, profile=profile)

        tier_info = get_tier_info(profile.lifetime_points, profile.available_points)

        return Response({
            'success': True,
            'message': 'Rewards points summary retrieved successfully.',
            'data': {
                'available_points': profile.available_points,
                'lifetime_points': profile.lifetime_points,
                'total_points': profile.available_points,
                'current_tier': profile.current_tier,
                'next_tier': tier_info['next_tier'],
                'points_to_next_tier': tier_info['points_to_next_tier'],
                'tier_progress_percentage': tier_info['tier_progress_percentage'],
                'exp_summary': tier_info['exp_summary'],
                'rules': {
                    'point_validity': '24 months from earn date',
                    'tier_preservation': 'Tier is based on lifetime achievement points and never degrades upon expiration',
                    'tiers': {
                        'Bronze': '0 - 2,000 pts',
                        'Silver': '2,000 - 5,000 pts',
                        'Gold': '5,000 - 10,000 pts',
                        'Platinum': '10,000 - 50,000 pts',
                        'Diamond': '50,000+ pts',
                    },
                    'earning_activities': {
                        'share_a_look': '120 points',
                        'invite_friends': '200 points',
                        'make_a_purchase': '200 points',
                        'add_to_closet': '50 points',
                    }
                }
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Rewards & Gamification"],
    summary="Points Transaction History",
    description="Paginated history of all points earned (e.g. sharing looks, scanning clothes, purchases) and expired.",
    responses={
        200: RewardPointTransactionSerializer(many=True),
    }
)
class RewardPointsHistoryView(generics.ListAPIView):
    """
    API endpoint to list points earning, expiring, and redemption history.
    
    GET /api/rewards/points/history/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = RewardPointTransactionSerializer
    pagination_class = StandardRewardsPagination

    def _get_reward_profile(self):
        if not hasattr(self, '_cached_reward_profile'):
            self._cached_reward_profile, _ = UserRewardProfile.objects.get_or_create(user=self.request.user)
        return self._cached_reward_profile

    def get_queryset(self):
        profile = self._get_reward_profile()
        has_expired = RewardPointTransaction.objects.filter(
            user=self.request.user,
            is_expired=False,
            expires_at__lte=timezone.now(),
            points__gt=0
        ).exists()
        if has_expired:
            process_expired_points(self.request.user, profile=profile)
        return RewardPointTransaction.objects.filter(user=self.request.user).order_by('-created_at')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        profile = self._get_reward_profile()
        response.data['available_points'] = profile.available_points
        response.data['lifetime_points'] = profile.lifetime_points
        response.data['current_tier'] = profile.current_tier
        return response


@extend_schema(
    tags=["Rewards & Gamification"],
    summary="Claim Affiliate Purchase Reward Points",
    description="Claim 200 reward points for a verified affiliate store purchase with order_id, store name, and amount.",
    responses={
        200: OpenApiResponse(description="200 reward points awarded successfully"),
        400: OpenApiResponse(description="Missing order_id or points already claimed"),
    }
)
class ClaimPurchaseRewardView(APIView):
    """
    API endpoint to claim 200 points for an affiliate purchase.
    
    POST /api/rewards/points/claim-purchase/
    Body: {"order_id": "ORD-12345", "store": "Zara", "amount": "89.99"}
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        from django.conf import settings
        if not getattr(settings, 'MYC_PURCHASE_MANUAL_CLAIM_ENABLED', False):
            return Response({
                'success': False,
                'message': 'Manual purchase claims are currently disabled. Purchase points are credited automatically via verified affiliate transactions.',
                'code': 'feature_disabled'
            }, status=status.HTTP_404_NOT_FOUND)

        order_id = request.data.get('order_id')
        store = request.data.get('store', 'Affiliate Store')
        amount = request.data.get('amount')

        if not order_id:
            return Response({
                'success': False,
                'message': 'order_id is required to claim purchase points.'
            }, status=status.HTTP_400_BAD_REQUEST)

        order_id_clean = str(order_id).strip()

        # Check for duplicate claim globally (SR-02)
        existing = RewardPointTransaction.objects.filter(
            action_type='make_purchase',
            reference_id=order_id_clean
        ).first()

        if existing:
            return Response({
                'success': False,
                'message': 'Reward points for this order have already been claimed.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check for existing affiliate conversion
        from affiliate.models import Conversion
        conversion = Conversion.objects.filter(
            order_reference=order_id_clean,
            user=request.user,
        ).first()

        if conversion and conversion.reward_claimed:
            return Response({
                'success': False,
                'message': 'Reward points for this order have already been claimed.'
            }, status=status.HTTP_400_BAD_REQUEST)

        desc = f"Purchase at {store}" + (f" (€{amount})" if amount else "")
        tx = award_points(
            user=request.user,
            action_type='make_purchase',
            description=desc,
            reference_id=order_id_clean,
            points_override=200
        )

        if not tx:
            return Response({
                'success': False,
                'message': 'Failed to process purchase reward claim. Duplicate or invalid order.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if conversion:
            conversion.reward_claimed = True
            conversion.reward_transaction = tx
            conversion.save(update_fields=['reward_claimed', 'reward_transaction'])

        return Response({
            'success': True,
            'message': 'Successfully claimed 200 reward points for your purchase!',
            'data': {
                'points_awarded': 200,
                'validity': '24 months',
                'order_id': order_id,
                'transaction_id': tx.id,
                'verified_conversion': bool(conversion),
            }
        }, status=status.HTTP_200_OK)
