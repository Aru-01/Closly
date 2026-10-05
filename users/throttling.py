"""
Rate limiting throttles for Closly Authentication and OTP endpoints.
Enforces a 2-minute (120-second) sliding window to protect against brute-force attacks.
"""
from rest_framework.throttling import SimpleRateThrottle
from django.core.cache import cache
from rest_framework.exceptions import Throttled

FAILED_ATTEMPTS_LIMIT = 5
LOCKOUT_DURATION = 900  # 15 minutes (900 seconds)


def record_failed_attempt(email, scope='otp'):
    """Increment failed attempt counter; triggers 15-minute lockout at threshold."""
    if not email:
        return
    email_clean = str(email).strip().lower()
    key = f"failed_attempts_{scope}_{email_clean}"
    try:
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, timeout=LOCKOUT_DURATION)
        if attempts >= FAILED_ATTEMPTS_LIMIT:
            cache.set(f"lockout_{scope}_{email_clean}", True, timeout=LOCKOUT_DURATION)
    except Exception:
        pass


def clear_failed_attempts(email, scope='otp'):
    """Reset attempt counter and lockout upon successful verification."""
    if not email:
        return
    email_clean = str(email).strip().lower()
    try:
        cache.delete(f"failed_attempts_{scope}_{email_clean}")
        cache.delete(f"lockout_{scope}_{email_clean}")
    except Exception:
        pass


def check_lockout(email, scope='otp'):
    """Returns True if the target account is currently locked out."""
    if not email:
        return False
    email_clean = str(email).strip().lower()
    try:
        return bool(cache.get(f"lockout_{scope}_{email_clean}"))
    except Exception:
        return False


class TwoMinuteRateThrottle(SimpleRateThrottle):
    """
    Base throttle class supporting custom duration specifications
    such as '5/120s' or '5/2m'.
    """

    def parse_rate(self, rate):
        if not rate:
            return (None, None)
        num, period = rate.split('/')
        num_requests = int(num)
        if period.endswith('s'):
            duration = int(period[:-1])
        elif period.endswith('m'):
            duration = int(period[:-1]) * 60
        elif period.endswith('h'):
            duration = int(period[:-1]) * 3600
        else:
            duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}.get(period[0], 120)
        return (num_requests, duration)


class OTPVerifyRateThrottle(TwoMinuteRateThrottle):
    """
    Limits OTP verification attempts to 5 attempts per 2 minutes.
    Throttles by client IP + targeted email to prevent brute-forcing OTPs.
    Also fails-closed if account is under 15-minute lockout.
    """
    scope = 'otp_verify'
    rate = '5/120s'

    def allow_request(self, request, view):
        email = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            email = str(request.data.get('email', '')).strip().lower()
        if email and check_lockout(email, scope='otp'):
            raise Throttled(detail="Too many failed attempts. This account is locked for 15 minutes.")
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            email = str(request.data.get('email', '')).strip().lower()
        if email:
            return f"throttle_otp_verify_{ident}_{email}"
        return f"throttle_otp_verify_{ident}"


class OTPResendRateThrottle(TwoMinuteRateThrottle):
    """
    Limits OTP resend requests to 3 requests per 2 minutes.
    Throttles by client IP + targeted email to prevent flooding SMTP mail quotas.
    """
    scope = 'otp_resend'
    rate = '3/120s'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            email = str(request.data.get('email', '')).strip().lower()
        if email:
            return f"throttle_otp_resend_{ident}_{email}"
        return f"throttle_otp_resend_{ident}"


class LoginRateThrottle(TwoMinuteRateThrottle):
    """
    Limits login attempts to 10 requests per 2 minutes per IP address.
    Protects against password brute-force and credential stuffing.
    """
    scope = 'login'
    rate = '10/120s'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return f"throttle_login_{ident}"


class PasswordResetRateThrottle(TwoMinuteRateThrottle):
    """
    Limits password reset requests to 5 requests per 2 minutes per IP + email.
    Enforces account lockout on excessive failed attempts.
    """
    scope = 'password_reset'
    rate = '5/120s'

    def allow_request(self, request, view):
        email = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            email = str(request.data.get('email', '')).strip().lower()
        if email and check_lockout(email, scope='pw_reset'):
            raise Throttled(detail="Too many failed attempts. This account is locked for 15 minutes.")
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            email = str(request.data.get('email', '')).strip().lower()
        if email:
            return f"throttle_pw_reset_{ident}_{email}"
        return f"throttle_pw_reset_{ident}"


class AIScanUserRateThrottle(SimpleRateThrottle):
    """
    Limits AI wardrobe garment scanning to 15 requests per minute per authenticated user
    to protect OpenAI API credits, GPU compute, and prevent resource exhaustion.
    """
    scope = 'ai_scan'
    rate = '15/min'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle_ai_scan_user_{request.user.id}"
        return f"throttle_ai_scan_ip_{self.get_ident(request)}"

