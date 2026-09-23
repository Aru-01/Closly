"""
Rate limiting throttles for Closly Authentication and OTP endpoints.
Enforces a 2-minute (120-second) sliding window to protect against brute-force attacks.
"""
from rest_framework.throttling import SimpleRateThrottle


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
    Throttles by client IP + targeted email to prevent brute-forcing 4-digit OTPs.
    """
    scope = 'otp_verify'
    rate = '5/120s'

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
    """
    scope = 'password_reset'
    rate = '5/120s'

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

