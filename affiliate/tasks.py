import logging
from zoneinfo import ZoneInfo
from datetime import timedelta
from celery import shared_task
from django.core.management import call_command
from django.utils import timezone
from django.db.models import Count, Q

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")

@shared_task(name='affiliate.tasks.sync_approved_brands_task')
def sync_approved_brands_task():
    """
    Automated periodic task to dynamically discover and update joined/approved brands
    from AWIN Programmes API and Rakuten Advertiser API.
    Runs prior to product feed sync to maintain an up-to-date Brand registry.
    """
    logger.info("Celery Task: Starting dynamic brand registry sync (AWIN & Rakuten)...")
    try:
        call_command('sync_approved_brands', network='all')
        logger.info("Celery Task: Dynamic brand registry sync completed successfully.")
        return "Dynamic brand registry sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Dynamic brand registry sync error: {e}", exc_info=True)
        raise


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


@shared_task(name='affiliate.tasks.reconcile_awin_transactions_task')
def reconcile_awin_transactions_task(days=30):
    """
    Daily automated reconciliation task (06:00 Berlin).
    Queries AWIN Transactions API, reconciles user attribution via clickrefs,
    and transitions PointAward states in the double-entry rewards ledger.
    """
    logger.info(f"Celery Task: Starting automated AWIN transactions reconciliation (past {days} days)...")
    try:
        call_command('reconcile_awin_transactions', days=days)
        logger.info("Celery Task: AWIN transactions reconciliation finished successfully.")
        return "AWIN transactions reconciliation completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: AWIN transactions reconciliation error: {e}", exc_info=True)
        raise


@shared_task(name='affiliate.tasks.generate_missing_embeddings_task')
def generate_missing_embeddings_task(limit=500):
    """
    Periodic task to process catalog products lacking FashionSigLIP 768-dim embeddings.
    """
    from affiliate.services.embedding_service import batch_generate_product_embeddings
    logger.info(f"Celery Task: Generating missing FashionSigLIP vector embeddings (limit {limit})...")
    try:
        count = batch_generate_product_embeddings(limit=limit)
        logger.info(f"Celery Task: Generated {count} vector embeddings.")
        return f"Generated {count} vector embeddings."
    except Exception as e:
        logger.error(f"Celery Task: Error generating embeddings: {e}", exc_info=True)
        raise


@shared_task(name='affiliate.tasks.ingest_event_batch_task')
def ingest_event_batch_task(user_id, events_data):
    """
    Asynchronous bulk ingestion of user behavioral events (impressions, clicks, swipes, saves)
    and incremental EMA taste vector updates.
    """
    from affiliate.models import AffiliateProduct, Event
    from affiliate.services.vector_engine import update_user_taste_vector
    from users.models import User

    if not events_data:
        return 0

    user = User.objects.filter(id=user_id).first()
    if not user:
        logger.warning(f"ingest_event_batch_task: User {user_id} not found.")
        return 0

    now = timezone.now()
    berlin_day = now.astimezone(BERLIN_TZ).date()

    product_ids = {
        e.get('product_id') for e in events_data
        if isinstance(e, dict) and e.get('product_id') is not None
    }
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
    vector_update_candidates = []

    for item in events_data:
        pid = item.get('product_id')
        if pid not in valid_product_ids:
            continue

        etype = item.get('event_type')
        eclass = class_map.get(etype, Event.CLASS_INTERACTION)

        client_ts_raw = item.get('client_ts')
        client_ts = None
        if client_ts_raw:
            try:
                from django.utils.dateparse import parse_datetime
                client_ts = parse_datetime(client_ts_raw) if isinstance(client_ts_raw, str) else client_ts_raw
            except Exception:
                client_ts = now
        else:
            client_ts = now

        instances.append(Event(
            user=user,
            event_class=eclass,
            event_type=etype,
            product_id=pid,
            source=str(item.get('source', 'for_you'))[:50],
            feed_page=item.get('feed_page'),
            dwell_ms=item.get('dwell_ms'),
            berlin_day=berlin_day,
            client_ts=client_ts or now,
        ))

        # Vector updates on interactive actions
        if etype in (
            Event.TYPE_LIKE,
            Event.TYPE_SAVE,
            Event.TYPE_CLICK_OUT,
            Event.TYPE_DETAIL_VIEW,
            Event.TYPE_SKIP,
            Event.TYPE_FAVORITE,
        ):
            vector_update_candidates.append((pid, etype))

    # Bulk insert with ignore_conflicts=True for deduplication of impressions
    if instances:
        Event.objects.bulk_create(instances, ignore_conflicts=True)

    # Process taste vector updates sequentially for this user
    for pid, etype in vector_update_candidates:
        try:
            update_user_taste_vector(user, pid, etype)
        except Exception as e:
            logger.warning(f"Error updating taste vector for user {user.id}, product {pid}: {e}")

    logger.info(
        f"Ingested {len(instances)} events asynchronously for user {user.id} "
        f"({len(vector_update_candidates)} vector updates)."
    )
    return len(instances)


@shared_task(name='affiliate.tasks.reconcile_rakuten_transactions_task')
def reconcile_rakuten_transactions_task(days=30):
    """
    Daily automated reconciliation task (06:30 Berlin).
    Queries Rakuten Advertising API, reconciles user attribution via u1 clickrefs,
    and transitions PointAward states in the double-entry rewards ledger.
    """
    logger.info(f"Celery Task: Starting automated Rakuten transactions reconciliation (past {days} days)...")
    try:
        call_command('reconcile_rakuten_transactions', days=days)
        logger.info("Celery Task: Rakuten transactions reconciliation finished successfully.")
        return "Rakuten transactions reconciliation completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Rakuten transactions reconciliation error: {e}", exc_info=True)
        raise
