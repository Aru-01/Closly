"""
affiliate/views/sprint_views.py
================================
Style Sprint (Daily 10-Card Swipe Deck) API Views (F2 / V1-API-10).
Features:
- GET /api/v1/feed/sprint/ : Returns daily 10-card swipe deck for today.
- POST /api/v1/feed/sprint/swipe/ : Submits swipe interactions (single or batch)
  updating Event log and StyleProfile taste vectors via pgvector EMA.
"""
from zoneinfo import ZoneInfo
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from affiliate.models import AffiliateProduct, Event, ProductFavorite
from affiliate.serializers import AffiliateProductListSerializer
from affiliate.services.vector_engine import (
    get_style_sprint_deck,
    update_user_taste_vector,
    BERLIN_TZ,
)


class StyleSprintView(APIView):
    """
    GET /api/v1/feed/sprint/
    Returns the daily personalized 10-card fashion swipe deck for Berlin date.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        today_berlin = timezone.now().astimezone(BERLIN_TZ).date()
        deck_cards, swiped_count, is_completed = get_style_sprint_deck(
            user=request.user,
            berlin_date=today_berlin,
            deck_size=10,
        )

        serializer = AffiliateProductListSerializer(
            deck_cards,
            many=True,
            context={'request': request}
        )

        return Response({
            'date': str(today_berlin),
            'completed': is_completed,
            'total_cards': 10,
            'swiped_count': swiped_count,
            'remaining_count': max(0, 10 - swiped_count),
            'cards': serializer.data,
            'message': (
                "You have completed today's Style Sprint! Check back tomorrow."
                if is_completed
                else "Swipe right to like, swipe left to skip, or swipe up to save."
            )
        }, status=status.HTTP_200_OK)


class StyleSprintSwipeView(APIView):
    """
    POST /api/v1/feed/sprint/swipe/
    Records swipe interactions (like / skip / save) on Style Sprint cards.
    Updates behavioral events and adjusts the user's 768-dim taste vector.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        today_berlin = timezone.now().astimezone(BERLIN_TZ).date()

        # Support both single swipe object and batch swipes array
        raw_swipes = request.data.get('swipes')
        if raw_swipes is None:
            # Single swipe payload
            product_id = request.data.get('product_id')
            action = request.data.get('action') or request.data.get('direction', 'like')
            if not product_id:
                return Response(
                    {'error': "Field 'product_id' is required.", 'code': 'MISSING_PRODUCT_ID'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raw_swipes = [{'product_id': product_id, 'action': action}]

        if not isinstance(raw_swipes, list) or len(raw_swipes) == 0:
            return Response(
                {'error': "Invalid swipe payload. Expected 'product_id' or 'swipes' list.", 'code': 'INVALID_PAYLOAD'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        processed_count = 0
        for item in raw_swipes:
            p_id = item.get('product_id')
            act = str(item.get('action') or item.get('direction') or 'like').strip().lower()

            try:
                product = AffiliateProduct.objects.get(id=p_id)
            except (AffiliateProduct.DoesNotExist, ValueError, TypeError):
                continue

            # Normalize event type
            if act in ('right', 'like', 'love'):
                event_type = Event.TYPE_LIKE
                event_act = 'like'
            elif act in ('left', 'skip', 'dislike'):
                event_type = Event.TYPE_SKIP
                event_act = 'skip'
            elif act in ('up', 'save', 'favorite'):
                event_type = Event.TYPE_SAVE
                event_act = 'save'
                ProductFavorite.objects.get_or_create(user=request.user, product=product)
            else:
                event_type = Event.TYPE_LIKE
                event_act = 'like'

            # Record event log
            Event.objects.create(
                user=request.user,
                product=product,
                event_class=Event.CLASS_INTERACTION,
                event_type=event_type,
                source='sprint',
                berlin_day=today_berlin,
            )

            # Update StyleProfile taste vector with EMA
            update_user_taste_vector(request.user, product.id, event_act)
            processed_count += 1

        # Calculate current total swiped count today
        current_swiped = Event.objects.filter(
            user=request.user,
            source='sprint',
            berlin_day=today_berlin,
        ).values('product_id').distinct().count()

        is_completed = current_swiped >= 10
        points_awarded = 0

        # Award completion points if user reached 10 cards today
        if is_completed:
            try:
                from rewards.models import PointAward
                # Check if completion award already granted today
                already_awarded = PointAward.objects.filter(
                    user=request.user,
                    reason__icontains='Style Sprint daily',
                    created_at__date=today_berlin,
                ).exists()

                if not already_awarded:
                    PointAward.objects.create(
                        user=request.user,
                        points=50,
                        reason=f"Style Sprint daily completion ({today_berlin})",
                        status='confirmed',
                    )
                    points_awarded = 50
            except Exception:
                pass

        return Response({
            'status': 'success',
            'processed_swipes': processed_count,
            'total_swiped_today': current_swiped,
            'completed': is_completed,
            'remaining_count': max(0, 10 - current_swiped),
            'points_awarded': points_awarded,
            'message': (
                "Congratulations! You completed today's Style Sprint!"
                if is_completed
                else "Swipe recorded successfully."
            )
        }, status=status.HTTP_200_OK)
