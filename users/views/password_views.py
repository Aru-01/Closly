import logging
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.authentication import FirebaseAuthentication
from users.serializers import (
    PasswordResetRequestSerializer,
    PasswordResetOTPVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordChangeSerializer,
)
from users.utils import send_password_reset_email
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to request password reset with 30-second rate limiting
    
    POST /api/users/password-reset/
    
    Request body:
    {
        "email": "john@example.com"
    }
    """
    
    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer
    
    def post(self, request):
        """Request password reset"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email']
            
            try:
                user = User.objects.get(email=email)
                
                # 30-second rate limiting check
                if user.otp_created_at:
                    seconds_passed = (timezone.now() - user.otp_created_at).total_seconds()
                    if seconds_passed < 30:
                        retry_after = int(30 - seconds_passed)
                        return standard_response(
                            success=False,
                            message=f"Please wait {retry_after} seconds before requesting another OTP.",
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS
                        )
                
                # Generate and send password reset OTP
                from users.utils import generate_otp, send_password_reset_email
                otp = generate_otp()
                user.otp = otp
                user.otp_created_at = timezone.now()
                user.password_reset_verified = False
                user.save(update_fields=['otp', 'otp_created_at', 'password_reset_verified'])
                send_password_reset_email(user, otp)
            
            except User.DoesNotExist:
                # For security, don't reveal if email exists or not
                pass
            
            # Always return success message
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


class PasswordResetOTPVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to verify OTP for password reset.
    On success, sets password_reset_verified=True and clears the OTP from DB.
    """
    permission_classes = [AllowAny]
    serializer_class = PasswordResetOTPVerifySerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            try:
                user = User.objects.get(email=email)
                if user.otp == otp and user.is_otp_valid():
                    # OTP is valid: allow password reset and remove OTP from database
                    user.password_reset_verified = True
                    user.clear_otp()
                    user.save(update_fields=['password_reset_verified'])
                    return standard_response(
                        success=True,
                        message="OTP verified successfully. You can now reset your password."
                    )
                else:
                    # Expired OTP is automatically cleared from the DB by is_otp_valid()
                    return standard_response(
                        success=False,
                        message="Invalid or expired OTP.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            except User.DoesNotExist:
                return standard_response(
                    success=False,
                    message="User not found.",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        return standard_response(
            success=False,
            message="Invalid data.",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to confirm password reset.
    Enforces that the user has verified the OTP (password_reset_verified=True).
    
    POST /api/users/password-reset-confirm/
    
    Request body:
    {
        "email": "john@example.com",
        "password": "NewSecurePass123!",
        "confirm_password": "NewSecurePass123!"
    }
    """
    
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    
    def post(self, request):
        """Confirm password reset"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email']
            new_password = serializer.validated_data['password']
            
            try:
                user = User.objects.get(email=email)
                
                # Security check: verify that user actually verified OTP
                if not user.password_reset_verified:
                    return standard_response(
                        success=False,
                        message="Password reset not authorized. Please verify your OTP first.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                # Set new password and reset verification flag
                user.set_password(new_password)
                user.password_reset_verified = False
                user.save(update_fields=['password', 'password_reset_verified'])
                
                return standard_response(
                    success=True,
                    message="Password has been reset successfully. You can now login with your new password.",
                    status_code=status.HTTP_200_OK
                )
            
            except User.DoesNotExist:
                return standard_response(
                    success=False,
                    message="User not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    """
    API endpoint to change password (authenticated user)
    
    POST /api/users/password-change/
    
    Request body:
    {
        "old_password": "OldPass123!",
        "new_password": "NewSecurePass123!",
        "confirm_password": "NewSecurePass123!"
    }
    """
    
    permission_classes = [IsAuthenticated]
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
            
            return standard_response(
                success=True,
                message="Password changed successfully",
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


