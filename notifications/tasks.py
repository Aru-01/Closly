from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(name='notifications.tasks.cleanup_old_notifications_task')
def cleanup_old_notifications_task(days=60):
    """
    Periodic task to permanently delete in-app notifications older than `days` (default 60 days).
    Runs daily via Celery Beat.
    """
    from .models import Notification
    cutoff_date = timezone.now() - timedelta(days=days)
    deleted_count, _ = Notification.objects.filter(created_at__lt=cutoff_date).delete()
    logger.info(f"Notification cleanup: {deleted_count} notifications older than {days} days deleted.")
    return f"{deleted_count} notifications older than {days} days deleted."
