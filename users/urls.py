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
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    
    # Password management
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset-otp-verify/', PasswordResetOTPVerifyView.as_view(), name='password-reset-otp-verify'),
    path('password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change'),
    path('change-password/', PasswordChangeView.as_view(), name='change-password'),
    
    # Profile management
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('account-delete/', AccountDeleteView.as_view(), name='account-delete'),
    path('set-language/', SetLanguageView.as_view(), name='set-language'),
    path('language/', SetLanguageView.as_view(), name='set-language-alias'),
    path('share-link/', ShareProfileAPIView.as_view(), name='share-link-alias'),

    # Account Deletion
    path('delete-account/', account_deletion_request_view, name='delete-account-form'),
    path('delete-account-request/', AccountDeletionAPIView.as_view(), name='delete-account-request'),
    path('verify-account-deletion/<uuid:token>/', VerifyAccountDeletionView.as_view(), name='verify_account_deletion'),

    # Profile Data Deletion
    path('delete-profile-data/', delete_profile_data_request_view, name='delete-profile-data-form'),
    path('delete-profile-data-request/', ProfileDataDeletionAPIView.as_view(), name='delete-profile-data-request'),
    path('verify-profile-data-deletion/<uuid:token>/', VerifyProfileDataDeletionView.as_view(), name='verify_profile_data_deletion'),

    # User Preferences & Onboarding
    path('preferences/', UserPreferenceView.as_view(), name='user-preferences'),
    path('onboarding/', UserPreferenceView.as_view(), name='user-onboarding'),
    path('onboarding/update/', UserPreferenceView.as_view(), name='user-onboarding-update'),


    # Profile Sharing
    path('profile/share/', ShareProfileAPIView.as_view(), name='profile-share'),
    path('profile/public/<str:user_id>/', PublicProfileWebView.as_view(), name='public-profile'),
]