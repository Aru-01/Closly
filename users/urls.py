from django.urls import path
from .views import (
    UserRegistrationView,
    UserLoginView,
    UserLogoutView,
    FirebaseAuthView,
    VerifyOTPView,
    ResendOTPView,
    PasswordResetRequestView,
    PasswordResetOTPVerifyView,
    PasswordResetConfirmView,
    PasswordChangeView,
    UserProfileView,
    AccountDeleteView,
    CustomTokenRefreshView,
    CustomTokenVerifyView,
    SetLanguageView,
    account_deletion_request_view,
    AccountDeletionAPIView,
    VerifyAccountDeletionView,
    delete_profile_data_request_view,
    ProfileDataDeletionAPIView,
    VerifyProfileDataDeletionView,
    UserPreferenceView,
    ShareProfileAPIView,
    PublicProfileWebView,
    GdprDataExportView,
    DeviceRegistrationView,
    InviteListView,
    InviteRedeemView,
)

app_name = 'users'

urlpatterns = [
    # Authentication endpoints
    path('signup/', UserRegistrationView.as_view(), name='signup'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('firebase-auth/', FirebaseAuthView.as_view(), name='firebase-auth'),
    
    # Token management
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', CustomTokenVerifyView.as_view(), name='token-verify'),
    
    # OTP verification
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend_otp'),
    
    # Password management
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset-otp-verify/', PasswordResetOTPVerifyView.as_view(), name='password-reset-otp-verify'),
    path('password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change'),
    
    # Profile management
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('account-delete/', AccountDeleteView.as_view(), name='account-delete'),
    path('set-language/', SetLanguageView.as_view(), name='set-language'),

    # Account Deletion
    path('delete-account/', account_deletion_request_view, name='delete-account-form'),
    path('delete-account-request/', AccountDeletionAPIView.as_view(), name='delete-account-request'),
    path('verify-account-deletion/<uuid:token>/', VerifyAccountDeletionView.as_view(), name='verify-account-deletion'),
    path('verify-account-deletion/<uuid:token>/', VerifyAccountDeletionView.as_view(), name='verify_account_deletion'),

    # Profile Data Deletion
    path('delete-profile-data/', delete_profile_data_request_view, name='delete-profile-data-form'),
    path('delete-profile-data-request/', ProfileDataDeletionAPIView.as_view(), name='delete-profile-data-request'),
    path('verify-profile-data-deletion/<uuid:token>/', VerifyProfileDataDeletionView.as_view(), name='verify-profile-data-deletion'),
    path('verify-profile-data-deletion/<uuid:token>/', VerifyProfileDataDeletionView.as_view(), name='verify_profile_data_deletion'),

    # User Preferences & Onboarding
    path('preferences/', UserPreferenceView.as_view(), name='preferences'),
    path('preferences/', UserPreferenceView.as_view(), name='user-preferences'),
    path('onboarding/', UserPreferenceView.as_view(), name='user-onboarding'),

    # Profile Sharing
    path('profile/share/', ShareProfileAPIView.as_view(), name='profile-share'),
    path('profile/public/<str:user_id>/', PublicProfileWebView.as_view(), name='public-profile'),

    # GDPR Data Export (U-05 / Art. 20)
    path('export/', GdprDataExportView.as_view(), name='gdpr-export'),

    # Push Notification Device Registration (U-29)
    path('devices/', DeviceRegistrationView.as_view(), name='devices'),

    # Invite Gate Management (V1-API-01, V1-API-02 / U-08)
    path('invites/', InviteListView.as_view(), name='invite-list'),
    path('invites/redeem/', InviteRedeemView.as_view(), name='invite-redeem'),
]