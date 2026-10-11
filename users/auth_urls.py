from django.urls import path
from users.views import (
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
    CustomTokenRefreshView,
    CustomTokenVerifyView,
)

app_name = 'auth'

urlpatterns = [
    # Registration & Authentication
    path('signup/', UserRegistrationView.as_view(), name='signup'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('firebase/', FirebaseAuthView.as_view(), name='firebase'),
    path('firebase-auth/', FirebaseAuthView.as_view(), name='firebase-auth'),

    # JWT Token Lifecycle
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', CustomTokenVerifyView.as_view(), name='token-verify'),

    # Email / Phone OTP Verification
    path('otp/verify/', VerifyOTPView.as_view(), name='otp-verify'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('otp/resend/', ResendOTPView.as_view(), name='otp-resend'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),

    # Password Reset & Security
    path('password/reset/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password/reset/verify/', PasswordResetOTPVerifyView.as_view(), name='password-reset-otp-verify'),
    path('password-reset-otp-verify/', PasswordResetOTPVerifyView.as_view(), name='password-reset-verify'),
    path('password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm-alt'),
    path('password/change/', PasswordChangeView.as_view(), name='password-change'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change-alt'),
]
