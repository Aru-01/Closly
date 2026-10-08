import logging
import secrets
from datetime import date
from django.db import transaction
from .email_utils import send_account_deletion_email

logger = logging.getLogger(__name__)


def generate_otp(length=6):
    """
    Generate a cryptographically secure numeric OTP of a given length (default 6 digits).
    """
    return f"{secrets.randbelow(10**length):0{length}d}"


def get_client_ip(request):
    """
    Get client IP address from request.
    Picks the last untrusted proxy hop when behind reverse proxies (NUM_PROXIES=1).
    
    Args:
        request: Django request object
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        proxies = [ip.strip() for ip in x_forwarded_for.split(',') if ip.strip()]
        ip = proxies[-1] if proxies else request.META.get('REMOTE_ADDR')
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip or '127.0.0.1'


def get_truncated_ip(ip_address):
    """
    Truncates an IP address for GDPR data minimization / Art. 5(1)(c) (U-25).
    IPv4: keeps /24 (e.g., '192.0.2.14' -> '192.0.2.0')
    IPv6: keeps /48 prefix
    """
    if not ip_address:
        return ''
    ip_str = ip_address.strip()
    if ':' in ip_str:
        # IPv6
        parts = ip_str.split(':')
        return ':'.join(parts[:3]) + '::/48'
    elif '.' in ip_str:
        # IPv4
        parts = ip_str.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    return ip_str


BLOCKED_SSRF_HOSTS = {
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    '169.254.169.254',
    'metadata.google.internal',
    'instance-data',
}


def is_ssrf_safe_url(url: str, allowed_schemes=('http', 'https')) -> bool:
    """
    Centralized SSRF protection (P-31, Spec Ch5 §4.4).
    Validates URL before server-side fetch:
    1. Scheme check (must be in allowed_schemes).
    2. Hostname blocklist (localhost, link-local, cloud metadata).
    3. TLD blocklist (.internal, .local, .onion, .arpa, .lan).
    4. DNS resolution validation: Resolved IP must NOT be loopback, private,
       link-local, reserved, or multicast.
    """
    import ipaddress
    import socket
    import urllib.parse

    if not url or not isinstance(url, str):
        return False

    url_clean = url.strip()
    try:
        parsed = urllib.parse.urlsplit(url_clean)
    except Exception:
        return False

    if parsed.scheme.lower() not in allowed_schemes:
        return False

    hostname = (parsed.hostname or '').strip().lower()
    if not hostname or hostname in BLOCKED_SSRF_HOSTS:
        return False

    if hostname.endswith(('.internal', '.local', '.onion', '.arpa', '.lan')):
        return False

    # Prevent direct IP matching blocked list
    try:
        direct_ip = ipaddress.ip_address(hostname)
        if (
            direct_ip.is_private or
            direct_ip.is_loopback or
            direct_ip.is_link_local or
            direct_ip.is_reserved or
            direct_ip.is_multicast
        ):
            return False
    except ValueError:
        pass

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private or
                ip_obj.is_loopback or
                ip_obj.is_link_local or
                ip_obj.is_reserved or
                ip_obj.is_multicast
            ):
                return False
    except Exception:
        return False

    return True


def get_user_agent(request):
    """
    Get user agent string from request.
    
    Args:
        request: Django request object
        
    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def get_minimized_user_agent(user_agent):
    """
    Returns a privacy-minimized SHA-256 hash prefix (16 chars) of the User-Agent (U-25).
    Prevents long-term browser fingerprint PII storage.
    """
    import hashlib
    if not user_agent:
        return ''
    return hashlib.sha256(user_agent.encode('utf-8')).hexdigest()[:16]


def record_user_consent(user, kind, granted=True, request=None, version='1.0'):
    """
    Records an auditable Consent event (ToS, privacy, photo AI processing, push notifications).
    Does not rely on a boolean field on User (U-21, Consent System).
    """
    from django.utils import timezone
    from users.models import Consent
    ip = ''
    ua = ''
    if request:
        ip = get_truncated_ip(get_client_ip(request))
        ua = get_minimized_user_agent(get_user_agent(request))
    return Consent.objects.create(
        user=user,
        kind=kind,
        granted=granted,
        version=version or '1.0',
        occurred_at=timezone.now(),
        ip_address=ip,
        user_agent=ua
    )


def has_user_consent(user, kind='photo_ai_processing', min_version=None):
    """
    Checks if user has actively granted consent for a specific category.
    Returns False if no consent is recorded, or if the latest consent record is granted=False.
    Server-side enforced gate for GDPR Article 7 compliance.
    """
    if not user or not user.is_authenticated:
        return False
    from users.models import Consent
    latest = Consent.objects.filter(user=user, kind=kind).order_by('-occurred_at').first()
    if not latest or not latest.granted:
        return False
    if min_version and hasattr(latest, 'version') and latest.version:
        try:
            from packaging import version as pkg_version
            if pkg_version.parse(latest.version) < pkg_version.parse(min_version):
                return False
        except Exception:
            pass
    return True



def calculate_age(date_of_birth):
    """
    Calculate age from date of birth.
    
    Args:
        date_of_birth (date): Date of birth
        
    Returns:
        int: Age in years
    """
    if not date_of_birth:
        return None
    
    today = date.today()
    age = today.year - date_of_birth.year
    
    # Adjust if birthday hasn't occurred this year
    if today.month < date_of_birth.month or \
       (today.month == date_of_birth.month and today.day < date_of_birth.day):
        age -= 1
    
    return age


def validate_age(date_of_birth, min_age=None):
    """
    Validate if user meets minimum age requirement.
    
    Args:
        date_of_birth (date): Date of birth
        min_age (int, optional): Minimum age required (defaults to settings.MYC_MIN_AGE or 16)
        
    Returns:
        bool: True if user meets age requirement, False otherwise
    """
    if min_age is None:
        from django.conf import settings
        min_age = getattr(settings, 'MYC_MIN_AGE', 16)

    age = calculate_age(date_of_birth)
    if age is None:
        return False
    return age >= min_age


def purge_and_anonymize_user(user):
    """
    Executes full GDPR-compliant account purge and user anonymization.
    1. Gathers final profile and wardrobe summary statistics.
    2. Sends account export and confirmation email to user's registered email.
    3. Purges all private content:
       - Closet items
       - Today outfits (posts, images, tags)
       - Story items, likes, views
       - Follows (both followers and followings)
       - Notifications
       - Rewards profile & transactions
       - Preferences and login history
    4. Deletes profile picture from storage.
    5. Anonymizes the user record:
       - name = 'Deleted User'
       - email = f"deleted_{uuid}@deleted.closly.app"
       - is_active = False
       - set_unusable_password()
       - clears PII (bio, location, dob, gender, etc.)
    6. Preserves past direct messages so chat partners don't lose their conversation history,
       while the counterpart author appears as 'Deleted User'.
    """
    # 1. Gather summary statistics before deletion
    summary = {
        'name': user.name,
        'email': user.email,
        'date_joined': user.date_joined.strftime('%d %B %Y') if user.date_joined else 'N/A',
        'closet_items_count': user.closet_items.count() if hasattr(user, 'closet_items') else 0,
        'outfits_count': user.today_outfits.count() if hasattr(user, 'today_outfits') else 0,
        'lifetime_points': getattr(getattr(user, 'reward_profile', None), 'lifetime_points', 0),
    }

    # 2. Send data export & confirmation email
    send_account_deletion_email(user, summary=summary)

    with transaction.atomic():
        # 3. Purge private user content (P-34)
        from closet.models import ClosetItem, FitCheck
        for item in ClosetItem.objects.filter(user=user):
            item.delete()
        for fc in FitCheck.objects.filter(user=user):
            fc.delete()

        from social.models import TodayOutfit, OutfitLike, Story, StoryView, StoryLike, UserFollow
        TodayOutfit.objects.filter(user=user).delete()
        OutfitLike.objects.filter(user=user).delete()
        Story.objects.filter(user=user).delete()
        StoryView.objects.filter(viewer=user).delete()
        StoryLike.objects.filter(user=user).delete()
        UserFollow.objects.filter(follower=user).delete()
        UserFollow.objects.filter(following=user).delete()

        from notifications.models import Notification
        Notification.objects.filter(recipient=user).delete()
        Notification.objects.filter(sender=user).delete()


        # 3.4 Financial Ledger Retention (SR-28):
        # Preserves double-entry auditability, but zeroes available balance and pseudonymizes all personal text descriptions.
        from rewards.models import UserRewardProfile, RewardPointTransaction, PointAward, LedgerTxn, AwardStateLog
        profile = UserRewardProfile.objects.filter(user=user).first()
        if profile:
            profile.available_points = 0
            profile.save(update_fields=['available_points'])

        RewardPointTransaction.objects.filter(user=user).update(
            description='Historical reward transaction (user pseudonymized for GDPR)'
        )
        RewardPointTransaction.objects.filter(reference_id=str(user.id)).update(
            reference_id='pseudonymized'
        )
        PointAward.objects.filter(referred_user=user).update(referred_user=None)
        LedgerTxn.objects.filter(award__user=user).update(
            description='Historical ledger transaction (user pseudonymized for GDPR)'
        )
        AwardStateLog.objects.filter(award__user=user).update(
            reason='State transition (user pseudonymized for GDPR)'
        )

        # Scrub user reference from affiliate conversions while retaining transaction data
        from affiliate.models import Conversion
        Conversion.objects.filter(user=user).update(user=None)

        from users.models import UserPreference, UserLoginHistory
        UserPreference.objects.filter(user=user).delete()
        UserLoginHistory.objects.filter(user=user).delete()

        # 4. Remove profile picture from disk
        if user.profile_picture:
            try:
                user.profile_picture.delete(save=False)
            except Exception as e:
                logger.error(f"Error deleting profile picture from storage for user {user.id}: {e}")

        # 5. Anonymize user record
        hex_id = str(user.id).replace('-', '')[:10]
        user.name = 'Deleted User'
        user.email = f"deleted_{hex_id}@deleted.myclosly.com"
        user.is_active = False
        user.is_email_verified = False
        user.is_subscribed = False
        user.set_unusable_password()
        user.profile_picture = None
        user.bio = None
        user.country = None
        user.city = None
        user.occupation = None
        user.gender = None
        user.date_of_birth = None
        user.firebase_uid = None
        user.otp = None
        user.referral_code = None
        user.save()

    # 6. Purge external identity records & clear cache outside atomic DB transaction
    if user.firebase_uid:
        try:
            from .firebase import delete_firebase_user
            delete_firebase_user(user.firebase_uid)
        except Exception as e:
            logger.warning(f"Non-critical: Firebase deletion failed for {user.id}: {e}")

    try:
        from .apple_auth import revoke_apple_token
        revoke_apple_token(user)
    except Exception as e:
        logger.warning(f"Non-critical: Apple token revocation failed for {user.id}: {e}")

    try:
        from django.core.cache import cache
        cache.delete(f"user_online_{user.id}")
        cache.delete(f"user_last_seen_{user.id}")
    except Exception as e:
        logger.warning(f"Non-critical: Cache clear failed for {user.id}: {e}")

    logger.info(f"User {user.id} successfully anonymized and content purged (GDPR).")
    return True
