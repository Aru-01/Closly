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
    # Authentication & Session
    path('signup/', UserRegistrationView.as_view(), name='signup'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('firebase-auth/', FirebaseAuthView.as_view(), name='firebase-auth'),
    
    # Token Lifecycle
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', CustomTokenVerifyView.as_view(), name='token-verify'),
    
    # OTP Verification
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    
    # Password Management
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset-otp-verify/', PasswordResetOTPVerifyView.as_view(), name='password-reset-otp-verify'),
    path('password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change'),
    
    # User Profile & Preferences
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('preferences/', UserPreferenceView.as_view(), name='preferences'),
    path('set-language/', SetLanguageView.as_view(), name='set-language'),
    path('profile/share/', ShareProfileAPIView.as_view(), name='profile-share'),
    path('profile/public/<str:user_id>/', PublicProfileWebView.as_view(), name='public-profile'),

    # Account Deletion & GDPR
    path('delete-account/', account_deletion_request_view, name='delete-account-form'),
    path('delete-account-request/', AccountDeletionAPIView.as_view(), name='delete-account-request'),
    path('verify-account-deletion/<str:token>/', VerifyAccountDeletionView.as_view(), name='verify-account-deletion'),
    path('account-delete/', AccountDeleteView.as_view(), name='account-delete'),

    # Profile Data Erasure (GDPR Right to Rectification/Erasure)
    path('delete-profile-data/', delete_profile_data_request_view, name='delete-profile-data-form'),
    path('delete-profile-data-request/', ProfileDataDeletionAPIView.as_view(), name='delete-profile-data-request'),
    path('verify-profile-data-deletion/<str:token>/', VerifyProfileDataDeletionView.as_view(), name='verify-profile-data-deletion'),

    # GDPR Data Portability Export (Art. 20)
    path('export/', GdprDataExportView.as_view(), name='gdpr-export'),

    # Device Registration (APNs / FCM)
    path('devices/', DeviceRegistrationView.as_view(), name='devices'),

    # Invite Gate Management
    path('invites/', InviteListView.as_view(), name='invite-list'),
    path('invites/redeem/', InviteRedeemView.as_view(), name='invite-redeem'),
]