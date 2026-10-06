from zoneinfo import ZoneInfo
from datetime import datetime
from django.utils import timezone
from django.db import transaction
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from affiliate.models import AffiliateProduct, Event
from affiliate.serializers import EventBatchSerializer
from affiliate.throttles import EventBatchRateThrottle

BERLIN_TZ = ZoneInfo("Europe/Berlin")


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Batch Ingest Behavioral Events",
    description=(
        "Batch ingestion endpoint for client behavioral discovery signals (impressions, "
        "detail views, likes, skips, saves, click-outs). Authenticated, max 200 events per batch, "
        "deduplicates same-day impressions, and updates user preference weighting foundation."
    ),
    request=EventBatchSerializer,
    responses={
        200: OpenApiResponse(description="Events processed successfully"),
        400: OpenApiResponse(description="Validation error in payload"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    }
)
class EventBatchView(APIView):
    """
    POST /api/affiliate/events/batch/
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
        user = request.user
        now = timezone.now()
        berlin_day = now.astimezone(BERLIN_TZ).date()

        # Validate that product_ids exist in database
        product_ids = {e['product_id'] for e in events_data}
        valid_product_ids = set(
            AffiliateProduct.objects.filter(id__in=product_ids).values_list('id', flat=True)
        )

        class_map = {
            Event.TYPE_IMPRESSION: Event.CLASS_IMPRESSION,
            Event.TYPE_DETAIL_VIEW: Event.CLASS_INTERACTION,
            Event.TYPE_LIKE: Event.CLASS_INTERACTION,
            Event.TYPE_SKIP: Event.CLASS_INTERACTION,
            Event.TYPE_SAVE: Event.CLASS_INTERACTION,
            Event.TYPE_CLICK_OUT: Event.CLASS_INTERACTION,
            Event.TYPE_FAVORITE: Event.CLASS_INTERACTION,
        }

        instances = []
        skipped_invalid = 0

        for item in events_data:
            pid = item['product_id']
            if pid not in valid_product_ids:
                skipped_invalid += 1
                continue

            etype = item['event_type']
            eclass = class_map.get(etype, Event.CLASS_INTERACTION)

            instances.append(Event(
                user=user,
                event_class=eclass,
                event_type=etype,
                product_id=pid,
                source=item.get('source', 'for_you')[:50],
                feed_page=item.get('feed_page'),
                dwell_ms=item.get('dwell_ms'),
                berlin_day=berlin_day,
                client_ts=item.get('client_ts') or now,
            ))

        # Bulk insert with ignore_conflicts=True for deduplication of (user, product, berlin_day, 'impression')
        if instances:
            Event.objects.bulk_create(instances, ignore_conflicts=True)

        return Response({
            'success': True,
            'message': 'Events processed successfully',
            'data': {
                'received': len(events_data),
                'accepted': len(instances),
                'ingested_count': len(instances),
                'skipped_invalid_products': skipped_invalid,
            }
        }, status=status.HTTP_201_CREATED)
