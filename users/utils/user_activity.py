from django.core.cache import cache
from django.utils import timezone

ONLINE_TIMEOUT = 300  # 5 minutes in seconds


def set_user_online(user_id):
    """Marks a user as active/online and records current activity timestamp."""
    if not user_id:
        return
    now_iso = timezone.now().isoformat()
    cache.set(f"user_online_{user_id}", True, timeout=ONLINE_TIMEOUT)
    cache.set(f"user_last_seen_{user_id}", now_iso, timeout=86400 * 30)


def set_user_offline(user_id):
    """Marks a user as offline and records departure timestamp."""
    if not user_id:
        return
    cache.delete(f"user_online_{user_id}")
    now_iso = timezone.now().isoformat()
    cache.set(f"user_last_seen_{user_id}", now_iso, timeout=86400 * 30)


def is_user_online(user_id):
    """Returns True if user has an active session/heartbeat within last 5 minutes."""
    if not user_id:
        return False
    return bool(cache.get(f"user_online_{user_id}"))


def get_user_last_seen(user, default=None):
    """Returns ISO datetime string for when user was last active or logged in."""
    if not user:
        return default
    user_id = getattr(user, 'id', user)
    last_seen = cache.get(f"user_last_seen_{user_id}")
    if last_seen:
        return last_seen
    if hasattr(user, 'last_login') and user.last_login:
        return user.last_login.isoformat()
    return default
