import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from affiliate.serializers import EventBatchSerializer
from affiliate.throttles import EventBatchRateThrottle
from affiliate.services.telemetry_services import queue_event_batch

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Batch Ingest Behavioral Events (Async)",
    description=(
        "Optimized client-side telemetry batch ingestion endpoint for user discovery signals "
        "(impressions, detail views, likes, skips, saves, click-outs). Authenticated, max 200 events per batch.\n\n"
        "Returns HTTP 202 Accepted immediately (<15ms). Deduplicates same-day impressions, stores events, "
        "and updates the user's 768-dimensional Taste Vector asynchronously via Celery."
    ),
    request=EventBatchSerializer,
    responses={
        202: OpenApiResponse(
            description="Event batch accepted for asynchronous processing",
            examples=[
                OpenApiExample(
                    "Success 202 Accepted",
                    value={
                        "success": True,
                        "message": "Event batch accepted for asynchronous ingestion",
                        "data": {
                            "queued_count": 3,
                            "ingested_count": 3,
                            "status": "processing"
                        }
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Validation error in payload"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    }
)
class EventBatchView(APIView):
    """
    Skinny View: Validates telemetry payload and delegates background queueing to telemetry_services.
    POST /api/v1/feed/events/batch/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [EventBatchRateThrottle]

    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'message': 'Invalid event batch payload',
                'errors': serializer.errors,
            }, status=status.HTTP_400_BAD_REQUEST)

        events_data = serializer.validated_data['events']
        result = queue_event_batch(request.user, events_data)

        return Response({
            'success': True,
            'message': 'Event batch accepted for asynchronous ingestion',
            'data': result,
        }, status=status.HTTP_202_ACCEPTED)
