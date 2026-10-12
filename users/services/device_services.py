import logging
from django.utils import timezone
from users.models import Device
from users.utils.common_utils import record_user_consent

logger = logging.getLogger(__name__)


def register_or_update_device(user, apns_token: str, platform: str = 'ios', prefs: dict = None, request=None):
    """
    Registers or updates an APNs or FCM push notification device token for a user.
    Records GDPR consent for push notifications.
    """
    if prefs is None:
        prefs = {}

    device, created = Device.objects.update_or_create(
        apns_token=apns_token,
        defaults={
            'user': user,
            'platform': platform or 'ios',
            'prefs': prefs,
            'last_seen': timezone.now(),
        }
    )

    # Record consent for push notifications (U-21, Consent System)
    try:
        record_user_consent(user, 'push_notification', granted=True, request=request)
    except Exception as e:
        logger.warning(f"Could not record push notification consent for user {user.id}: {e}")

    logger.info(f"Device {device.id} ({platform}) {'registered' if created else 'updated'} for user {user.id}")
    return device, created
