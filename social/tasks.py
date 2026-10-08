from celery import shared_task
from django.utils import timezone
import logging

from datetime import timedelta

logger = logging.getLogger(__name__)


@shared_task(name='social.tasks.expire_old_stories_task')
def expire_old_stories_task():
    """
    Periodic task to:
    1. Mark stories older than 24 hours (or past expires_at) as inactive.
    2. Purge image files and database rows for stories expired more than 7 days ago (SR-11).
    Runs hourly via Celery Beat.
    """
    from .models import Story
    now = timezone.now()
    count = Story.objects.filter(is_active=True, expires_at__lte=now).update(is_active=False)
    logger.info(f"Story cleanup: {count} stories deactivated.")

    # Retention cleanup: purge media files and rows older than MYC_STORY_RETENTION_DAYS (SR-11, SR-23)
    from django.conf import settings
    retention_days = getattr(settings, 'MYC_STORY_RETENTION_DAYS', 7)
    retention_cutoff = now - timedelta(days=retention_days)
    old_stories = Story.objects.filter(expires_at__lte=retention_cutoff)
    purged_count = 0
    for s in old_stories:
        if s.image and hasattr(s.image, 'storage') and s.image.name:
            try:
                s.image.storage.delete(s.image.name)
            except Exception as e:
                logger.warning(f"Error purging image for expired Story {s.id}: {e}")
        s.delete()
        purged_count += 1

    if purged_count > 0:
        logger.info(f"Story retention purge: {purged_count} stories older than 7 days permanently removed.")

    return f"{count} expired stories deactivated, {purged_count} purged."
