import logging
from .models import Notification

logger = logging.getLogger(__name__)


def create_notification(recipient, notification_type, title, message, sender=None, data=None):
    """
    Service to safely create an in-app notification for a recipient user.
    """
    if not recipient:
        return None

    # Don't notify if the action is triggered by the recipient themselves (e.g. self-like)
    if sender and getattr(sender, 'id', None) == getattr(recipient, 'id', None):
        return None

    try:
        notification = Notification.objects.create(
            recipient=recipient,
            sender=sender,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data or {}
        )
        return notification
    except Exception as e:
        recipient_id = getattr(recipient, 'id', recipient)
        logger.error(f"Failed to create notification for user {recipient_id}: {e}")
        return None
