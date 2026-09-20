from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(name='social.tasks.expire_old_stories_task')
def expire_old_stories_task():
    """
    Periodic task to mark stories older than 24 hours (or past expires_at) as inactive.
    Runs hourly via Celery Beat.
    """
    from .models import Story
    now = timezone.now()
    count = Story.objects.filter(is_active=True, expires_at__lte=now).update(is_active=False)
    logger.info(f"Story cleanup: {count} stories deactivated.")
    return f"{count} expired stories deactivated."

