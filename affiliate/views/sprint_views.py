import logging
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from affiliate.serializers import AffiliateProductListSerializer
from affiliate.services.vector_engine import (
    get_style_sprint_deck,
    BERLIN_TZ,
)
from affiliate.services.sprint_services import (
    process_swipe_interactions,
)

logger = logging.getLogger(__name__)


class StyleSprintView(APIView):
    """
    Skinny View: Returns the daily personalized 10-card fashion swipe deck for Berlin date.
    GET /api/v1/feed/sprint/
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
    Skinny View: Records swipe interactions (like / skip / save) on Style Sprint cards.
    Delegates bulk event logging and taste vector adjustment to sprint_services.
    POST /api/v1/feed/sprint/swipe/
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        raw_swipes = request.data.get('swipes')
        if raw_swipes is None:
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

        processed_count, current_swiped, is_completed, points_awarded = process_swipe_interactions(
            user=request.user,
            raw_swipes=raw_swipes,
        )

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
