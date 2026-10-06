import logging
from zoneinfo import ZoneInfo
from datetime import timedelta
from celery import shared_task
from django.core.management import call_command
from django.utils import timezone
from django.db.models import Count, Q

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")


@shared_task(name='affiliate.tasks.sync_awin_feeds_task')
def sync_awin_feeds_task():
    """
    Automated periodic task to download and bulk-upsert Awin gzip CSV feeds.
    Safely logs and re-raises exceptions so Celery accurately marks failures.
    """
    logger.info("Celery Task: Starting automated Awin affiliate products sync...")
    try:
        call_command('sync_awin_feeds')
        logger.info("Celery Task: Awin affiliate sync completed successfully.")
        return "Awin sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Awin affiliate sync error: {e}", exc_info=True)
        # Re-raise so Celery, flower, and error monitoring report actual task failure
        raise


@shared_task(name='affiliate.tasks.sync_rakuten_feeds_task')
def sync_rakuten_feeds_task():
    """
    Automated periodic task to sync products from Rakuten Advertising.
    Safely logs and re-raises exceptions so Celery accurately marks failures.
    """
    logger.info("Celery Task: Starting automated Rakuten affiliate products sync...")
    try:
        call_command('sync_rakuten_feeds')
        logger.info("Celery Task: Rakuten affiliate sync completed successfully.")
        return "Rakuten sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Rakuten affiliate sync error: {e}", exc_info=True)
        # Re-raise so Celery reports actual task failure
        raise


@shared_task(name='affiliate.tasks.aggregate_feed_impressions_daily_task')
def aggregate_feed_impressions_daily_task(target_date_str=None):
    """
    Nightly aggregate task that rolls up product-level behavioral discovery events
    into FeedImpressionsDaily records for the specified Berlin day.
    """
    from affiliate.models import Event, FeedImpressionsDaily, AffiliateProduct

    if target_date_str:
        from datetime import date
        target_date = date.fromisoformat(target_date_str)
    else:
        # Default to yesterday in Berlin timezone
        target_date = (timezone.now().astimezone(BERLIN_TZ) - timedelta(days=1)).date()

    logger.info(f"Starting feed impressions aggregation for Berlin date: {target_date}")

    # Aggregate events per product
    aggregates = (
        Event.objects.filter(berlin_day=target_date)
        .values('product_id')
        .annotate(
            impressions=Count('id', filter=Q(event_type=Event.TYPE_IMPRESSION)),
            detail_views=Count('id', filter=Q(event_type=Event.TYPE_DETAIL_VIEW)),
            saves=Count('id', filter=Q(event_type=Event.TYPE_SAVE)),
            clicks=Count('id', filter=Q(event_type=Event.TYPE_CLICK_OUT)),
            likes=Count('id', filter=Q(event_type=Event.TYPE_LIKE)),
            skips=Count('id', filter=Q(event_type=Event.TYPE_SKIP)),
        )
    )

    product_ids = [row['product_id'] for row in aggregates]
    brand_map = dict(
        AffiliateProduct.objects.filter(id__in=product_ids).values_list('id', 'brand')
    )

    count = 0
    for row in aggregates:
        pid = row['product_id']
        brand_name = brand_map.get(pid, 'Unknown')
        FeedImpressionsDaily.objects.update_or_create(
            berlin_day=target_date,
            product_id=pid,
            defaults={
                'brand_name': brand_name,
                'impressions_count': row['impressions'],
                'detail_views_count': row['detail_views'],
                'saves_count': row['saves'],
                'clicks_count': row['clicks'],
                'likes_count': row['likes'],
                'skips_count': row['skips'],
            }
        )
        count += 1

    logger.info(f"Aggregated impressions for {count} products on {target_date}.")
    return f"Aggregated {count} products for {target_date}."


@shared_task(name='affiliate.tasks.sync_shopify_feeds_task')
def sync_shopify_feeds_task():
    """
    Automated periodic task to sync independent brand products from Shopify public feeds.
    Safely logs and re-raises exceptions so Celery accurately marks failures.
    """
    logger.info("Celery Task: Starting automated Shopify feeds sync...")
    try:
        call_command('sync_shopify_feeds')
        logger.info("Celery Task: Shopify feeds sync completed successfully.")
        return "Shopify sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Shopify feeds sync error: {e}", exc_info=True)
        raise
