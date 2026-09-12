"""
Users utility package. Re-exports all utilities to maintain 100% backward compatibility.
"""

from .firebase import (
    initialize_firebase,
    verify_firebase_token,
)
from .email_utils import (
    send_otp_email,
    send_password_reset_email,
    send_welcome_email,
    send_account_deletion_email,
)
from .media_utils import (
    LOCAL_DEV_HOSTS,
    _normalize_media_url,
    build_absolute_media_url,
)
from .common_utils import (
    generate_otp,
    get_client_ip,
    get_user_agent,
    calculate_age,
    validate_age,
    purge_and_anonymize_user,
)

__all__ = [
    'initialize_firebase',
    'verify_firebase_token',
    'send_otp_email',
    'send_password_reset_email',
    'send_welcome_email',
    'send_account_deletion_email',
    'LOCAL_DEV_HOSTS',
    '_normalize_media_url',
    'build_absolute_media_url',
    'generate_otp',
    'get_client_ip',
    'get_user_agent',
    'calculate_age',
    'validate_age',
    'purge_and_anonymize_user',
]
