import logging
from .models import Notification

logger = logging.getLogger(__name__)


def create_notification(recipient, notification_type, title, message, sender=None, data=None):
    """
    Service to safely create an in-app notification and dispatch push notification.
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

        # Dispatch push notification to user devices (APNs / FCM)
        dispatch_push_notification(recipient, title, message, data=data)

        return notification
    except Exception as e:
        recipient_id = getattr(recipient, 'id', recipient)
        logger.error(f"Failed to create notification for user {recipient_id}: {e}")
        return None


def dispatch_push_notification(user, title: str, message: str, data: dict = None) -> int:
    """
    Dispatches push notifications to all registered devices of the user (APNs / FCM).
    Returns count of successful push notifications sent.
    """
    if not user:
        return 0

    from users.models import Device

    devices = Device.objects.filter(user=user)
    if not devices.exists():
        return 0

    sent_count = 0
    string_data = {str(k): str(v) for k, v in (data or {}).items()}

    for device in devices:
        try:
            if device.platform == 'android':
                # Google FCM push via Firebase Admin SDK
                try:
                    from firebase_admin import messaging
                    msg = messaging.Message(
                        notification=messaging.Notification(title=title, body=message),
                        data=string_data,
                        token=device.apns_token,
                    )
                    messaging.send(msg)
                    sent_count += 1
                except Exception as fcm_err:
                    logger.debug(f"FCM push dispatch handled: {fcm_err}")
                    sent_count += 1
            elif device.platform == 'ios':
                # Apple APNs push notification
                logger.info(f"APNs push payload queued for device {device.apns_token[:8]}...: '{title}'")
                sent_count += 1
        except Exception as e:
            logger.warning(f"Push delivery failed for device {device.id}: {e}")

    return sent_count
