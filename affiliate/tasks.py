from celery import shared_task
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


@shared_task(name='affiliate.tasks.sync_awin_feeds_task')
def sync_awin_feeds_task():
    """
    Automated periodic task to download and bulk-upsert Awin gzip CSV feeds.
    Deactivates obsolete products in O(1) query.
    """
    logger.info("Celery Task: Starting automated Awin affiliate products sync...")
    try:
        call_command('sync_awin_feeds')
        logger.info("Celery Task: Awin affiliate sync completed successfully.")
        return "Awin sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Awin affiliate sync error: {e}")
        return f"Awin sync failed: {e}"


@shared_task(name='affiliate.tasks.sync_rakuten_feeds_task')
def sync_rakuten_feeds_task():
    """
    Automated periodic task to sync products from Rakuten Advertising.
    """
    logger.info("Celery Task: Starting automated Rakuten affiliate products sync...")
    try:
        call_command('sync_rakuten_feeds')
        logger.info("Celery Task: Rakuten affiliate sync completed successfully.")
        return "Rakuten sync completed successfully."
    except Exception as e:
        logger.error(f"Celery Task: Rakuten affiliate sync error: {e}")
        return f"Rakuten sync failed: {e}"
