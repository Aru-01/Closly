import logging
import secrets
import hashlib
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from users.serializers import (
    PasswordResetRequestSerializer,
    PasswordResetOTPVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordChangeSerializer,
)
from users.utils import send_password_reset_email, generate_otp, revoke_all_user_tokens
from users.throttling import (
    PasswordResetRateThrottle,
    OTPVerifyRateThrottle,
    check_lockout,
    record_failed_attempt,
    clear_failed_attempts,
)
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

@extend_schema(
    tags=["Authentication & Security"],
    summary="Request Password Reset OTP",
    description="Sends a 6-digit password reset OTP to user's registered email address (throttled to once per 2 minutes).",
    request=PasswordResetRequestSerializer,
    responses={
        200: OpenApiResponse(description="Password reset OTP dispatched to email"),
        400: OpenApiResponse(description="Invalid email format"),
        429: OpenApiResponse(description="Rate limit exceeded, retry after cooldown"),
    }
)
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]
    serializer_class = PasswordResetRequestSerializer
    
    def post(self, request):
        """Request password reset"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email']
            
            if check_lockout(email, scope='pw_reset'):
                return standard_response(
                    success=False,
                    message="Too many failed attempts. This account is locked for 15 minutes.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            try:
                user = User.objects.get(email=email)
                
                # 2-minute (120-second) cooldown check
                if user.otp_created_at:
                    seconds_passed = (timezone.now() - user.otp_created_at).total_seconds()
                    if seconds_passed < 120:
                        retry_after = int(120 - seconds_passed)
                        return standard_response(
                            success=False,
                            message=f"Please wait {retry_after} seconds before requesting another OTP.",
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS
                        )
                
                # Generate and send 6-digit password reset OTP
                otp = generate_otp(6)
                user.otp = otp
                user.otp_created_at = timezone.now()
                user.password_reset_verified = False
                user.save(update_fields=['otp', 'otp_created_at', 'password_reset_verified'])
                send_password_reset_email(user, otp)
            
            except User.DoesNotExist:
                # Anti-enumeration: uniform response for nonexistent emails
                pass
            
            return standard_response(
                success=True,
                message="If an account with that email exists, a password reset OTP has been sent.",
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@extend_schema(
    tags=["Authentication & Security"],
    summary="Verify Password Reset OTP",
    description="Verifies the 6-digit password reset OTP and issues a single-use 15-minute cryptographic reset token.",
    request=PasswordResetOTPVerifySerializer,
    responses={
        200: OpenApiResponse(description="OTP verified; reset token issued"),
        400: OpenApiResponse(description="Invalid or expired OTP"),
        429: OpenApiResponse(description="Account locked due to too many attempts"),
    }
)
class PasswordResetOTPVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyRateThrottle]
    serializer_class = PasswordResetOTPVerifySerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            if check_lockout(email, scope='pw_reset'):
                return standard_response(
                    success=False,
                    message="Too many failed attempts. This account is locked for 15 minutes.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            try:
                user = User.objects.get(email=email)
                # Constant-time comparison
                if user.otp and secrets.compare_digest(str(user.otp), str(otp)) and user.is_otp_valid():
                    user.clear_otp()
                    clear_failed_attempts(email, scope='pw_reset')

                    # Generate single-use cryptographic reset token with 15-min TTL (U-16)
                    raw_reset_token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(raw_reset_token.encode('utf-8')).hexdigest()
                    cache.set(f"pw_reset_token_{token_hash}", str(user.id), timeout=900)

                    return standard_response(
                        success=True,
                        message="OTP verified successfully. You can now reset your password.",
                        data={'reset_token': raw_reset_token}
                    )
                else:
                    record_failed_attempt(email, scope='pw_reset')
                    return standard_response(
                        success=False,
                        message="Invalid email or verification code.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                        code="INVALID_OTP"
                    )
            except User.DoesNotExist:
                return standard_response(
                    success=False,
                    message="Invalid email or verification code.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="INVALID_OTP"
                )
        return standard_response(
            success=False,
            message="Invalid data.",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@extend_schema(
    tags=["Authentication & Security"],
    summary="Confirm Password Reset",
    description="Sets a new password using the verified single-use reset token and revokes all active sessions.",
    request=PasswordResetConfirmSerializer,
    responses={
        200: OpenApiResponse(description="Password reset successful; all active sessions revoked"),
        400: OpenApiResponse(description="Invalid or expired reset token"),
    }
)
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetRateThrottle]
    serializer_class = PasswordResetConfirmSerializer
    
    def post(self, request):
        """Confirm password reset with cryptographic reset token"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email']
            reset_token = serializer.validated_data['reset_token']
            new_password = serializer.validated_data['password']
            
            try:
                user = User.objects.get(email=email)
                
                # Validate cryptographic reset token from cache (U-16)
                token_hash = hashlib.sha256(reset_token.encode('utf-8')).hexdigest()
                cached_user_id = cache.get(f"pw_reset_token_{token_hash}")

                if not cached_user_id or str(cached_user_id) != str(user.id):
                    return standard_response(
                        success=False,
                        message="Invalid, expired, or already-used password reset token. Please request a new OTP.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                # Invalidate reset token immediately (single-use guarantee)
                cache.delete(f"pw_reset_token_{token_hash}")

                # Set new password
                user.set_password(new_password)
                user.password_reset_verified = False
                user.save(update_fields=['password', 'password_reset_verified'])
                
                # Revoke / blacklist all active user tokens upon password reset (U-06)
                revoke_all_user_tokens(user)

                return standard_response(
                    success=True,
                    message="Password has been reset successfully. All active sessions have been revoked. Please log in with your new password.",
                    status_code=status.HTTP_200_OK
                )
            
            except User.DoesNotExist:
                return standard_response(
                    success=False,
                    message="Invalid password reset request.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@extend_schema(
    tags=["Authentication & Security"],
    summary="Change Password (Authenticated)",
    description="Change account password for currently authenticated user by providing old and new password.",
    request=PasswordChangeSerializer,
    responses={
        200: OpenApiResponse(description="Password changed successfully; outstanding tokens revoked"),
        400: OpenApiResponse(description="Incorrect current password or invalid new password"),
    }
)
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = PasswordChangeSerializer
    
    def post(self, request):
        """Change password for authenticated user"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = request.user
            old_password = serializer.validated_data['old_password']
            new_password = serializer.validated_data['new_password']
            
            # Verify old password
            if not user.check_password(old_password):
                return standard_response(
                    success=False,
                    message="Current password is incorrect",
                    errors={'old_password': ['Current password is incorrect']},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Set new password
            user.set_password(new_password)
            user.save()

            # Revoke all outstanding tokens on password change (U-06)
            revoke_all_user_tokens(user)
            
            return standard_response(
                success=True,
                message="Password changed successfully. Please log in with your new credentials.",
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


