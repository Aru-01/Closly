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
    Delegates to users.services.gdpr_services.purge_and_anonymize_user for complete
    physical cloud storage unlinking, Apple OAuth token revocation, and anonymization.
    """
    from users.services.gdpr_services import purge_and_anonymize_user as _purge
    return _purge(user)

