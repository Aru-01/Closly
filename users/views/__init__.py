"""
Modular views package for users app.
Re-exports all view classes and helper functions for 100% backward compatibility.
"""

from django.core.mail import send_mail
from .base import standard_response
from .gdpr_views import (
    delete_profile_data_request_view,
    ProfileDataDeletionAPIView,
    VerifyProfileDataDeletionView,
    account_deletion_request_view,
    AccountDeletionAPIView,
    VerifyAccountDeletionView,
    AccountDeleteView,
)
from .auth_views import (
    UserRegistrationView,
    UserLoginView,
    UserLogoutView,
    FirebaseAuthView,
    VerifyOTPView,
    ResendOTPView,
    CustomTokenRefreshView,
    CustomTokenVerifyView,
)
from .password_views import (
    PasswordResetRequestView,
    PasswordResetOTPVerifyView,
    PasswordResetConfirmView,
    PasswordChangeView,
)
from .profile_views import (
    UserProfileView,
    SetLanguageView,
    UserPreferenceView,
    ShareProfileAPIView,
    PublicProfileWebView,
)
__all__ = [
    'standard_response',
    'delete_profile_data_request_view',
    'ProfileDataDeletionAPIView',
    'VerifyProfileDataDeletionView',
    'account_deletion_request_view',
    'AccountDeletionAPIView',
    'VerifyAccountDeletionView',
    'AccountDeleteView',
    'UserRegistrationView',
    'UserLoginView',
    'UserLogoutView',
    'FirebaseAuthView',
    'VerifyOTPView',
    'ResendOTPView',
    'CustomTokenRefreshView',
    'CustomTokenVerifyView',
    'PasswordResetRequestView',
    'PasswordResetOTPVerifyView',
    'PasswordResetConfirmView',
    'PasswordChangeView',
    'UserProfileView',
    'SetLanguageView',
    'UserPreferenceView',
    'ShareProfileAPIView',
    'PublicProfileWebView',
]
