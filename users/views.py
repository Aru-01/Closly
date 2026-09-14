from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.mail import send_mail
from django.urls import reverse
from django.contrib.auth import get_user_model # Move get_user_model here

# Create your views here.
"""
API Views for user authentication and profile management
All views return standardized response format
"""

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .authentication import FirebaseAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from .serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    FirebaseAuthSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetOTPVerifySerializer,
    ResendOTPSerializer,
    VerifyOTPSerializer,
    PasswordChangeSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    AccountDeleteSerializer,
    LanguagePreferenceSerializer,
)
from .utils import (
    verify_firebase_token,
    send_welcome_email,
    send_account_deletion_email,
    send_password_reset_email,
    get_client_ip,
    get_user_agent,
)
from .models import UserLoginHistory, AccountDeletionRequest, ProfileDataDeletionRequest
from django.shortcuts import render

@csrf_exempt
def delete_profile_data_request_view(request):
    return render(request, 'users/delete_profile_data_request.html')

@method_decorator(csrf_exempt, name='dispatch')
class ProfileDataDeletionAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return render(request, 'users/delete_profile_data_request.html', {'error': 'Email is required.'})

        user = User.objects.filter(email=email).first()
        if user:
            deletion_request, created = ProfileDataDeletionRequest.objects.get_or_create(user=user, defaults={'email': email})
            
            verification_link = request.build_absolute_uri(
                reverse('users:verify_profile_data_deletion', kwargs={'token': str(deletion_request.verification_token)})
            )
            
            send_mail(
                'Verify Profile Data Deletion Request',
                f'Click the following link to delete your profile data: {verification_link}',
                'from@example.com',
                [email],
                fail_silently=False,
            )
        return render(request, 'users/delete_profile_data_submitted.html')

class VerifyProfileDataDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            deletion_request = ProfileDataDeletionRequest.objects.get(verification_token=token, status='pending')
            if deletion_request.user:
                user = deletion_request.user
                user.name = "User"
                user.date_of_birth = None
                user.gender = None
                user.occupation = None
                user.country = None
                user.bio = None
                if user.profile_picture:
                    user.profile_picture.delete(save=False)
                user.save()
                
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/delete_profile_data_confirmed.html')
            else:
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/delete_profile_data_confirmed.html')
        except ProfileDataDeletionRequest.DoesNotExist:
            return standard_response(success=False, message="Invalid or expired verification link.", status_code=status.HTTP_400_BAD_REQUEST)


User = get_user_model()

@csrf_exempt
def account_deletion_request_view(request):
    return render(request, 'users/delete_account.html')
@method_decorator(csrf_exempt, name='dispatch')
class AccountDeletionAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        name = request.data.get('name')
        email = request.data.get('email')

        if not name or not email:
            return render(request, 'users/delete_account.html', {'error': 'Name and email are required.'})

        user = User.objects.filter(email=email).first()
        if user:
            deletion_request, created = AccountDeletionRequest.objects.get_or_create(user=user, defaults={'name': name, 'email': email})

            # Create a verification link
            verification_link = request.build_absolute_uri(
                reverse('users:verify_account_deletion', kwargs={'token': str(deletion_request.verification_token)})
            )

            # Send email to the user
            send_mail(
                'Verify Account Deletion Request',
                f'Click the following link to delete your account: {verification_link}',
                'from@example.com',  # Replace with your sending email
                [email],
                fail_silently=False,
            )
        return render(request, 'users/deletion_request_submitted.html')


class VerifyAccountDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            deletion_request = AccountDeletionRequest.objects.get(verification_token=token, status='pending')
            if deletion_request.user:
                deletion_request.user.delete()
                deletion_request.user = None
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/deletion_confirmed.html')
            else:
                # Handle case where user is not found, but request exists
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/deletion_confirmed.html')
        except AccountDeletionRequest.DoesNotExist:
            return standard_response(success=False, message="Invalid or expired verification link.", status_code=status.HTTP_400_BAD_REQUEST)



def standard_response(success=True, message="", data=None, errors=None, status_code=status.HTTP_200_OK):
    """
    Create standardized API response
    
    Args:
        success (bool): Whether operation was successful
        message (str): Response message
        data (dict): Response data
        errors (dict): Error details (for failed operations)
        status_code (int): HTTP status code
        
    Returns:
        Response: DRF Response object with standardized format
    """
    response_data = {
        'success': success,
        'message': message,
    }
    
    if data is not None:
        response_data['data'] = data
    
    if errors is not None:
        response_data['errors'] = errors
    
    return Response(response_data, status=status_code)


class UserRegistrationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint for user registration (signup)
    
    POST /api/users/signup/
    
    Request body:
    {
        "name": "John Doe",
        "email": "john@example.com",
        "date_of_birth": "1990-01-15",
        "password": "SecurePass123!",
        "confirm_password": "SecurePass123!"
    }
    """
    
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer
    
    def post(self, request):
        """Handle user registration"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            
            return standard_response(
                success=True,
                message="Registration successful. Please check your email for the OTP to verify your account.",
                data={
                    'user': {
                        'id': str(user.id),
                        'email': user.email,
                        'name': user.name,
                        'is_email_verified': user.is_email_verified,
                    }
                },
                status_code=status.HTTP_201_CREATED
            )
        
        return standard_response(
            success=False,
            message="Registration failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


class UserLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint for user login
    
    POST /api/users/login/
    
    Request body:
    {
        "email": "john@example.com",
        "password": "SecurePass123!"
    }
    """
    
    permission_classes = [AllowAny]
    serializer_class = UserLoginSerializer
    
    def post(self, request):
        """Handle user login"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = serializer.validated_data['user']
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)
            
            # Update last login
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
            
            # Log login history
            UserLoginHistory.objects.create(
                user=user,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
                auth_method='email'
            )
            
            # Check onboarding completion status
            onboarding_completed = (
                hasattr(user, 'preferences') and user.preferences.onboarding_completed
            ) or False

            profile_picture_url = request.build_absolute_uri(user.profile_picture.url) if user.profile_picture else None

            # Return success response with tokens
            return standard_response(
                success=True,
                message="Login successful",
                data={
                    'user': {
                        'id': str(user.id),
                        'email': user.email,
                        'name': user.name,
                        'is_email_verified': user.is_email_verified,
                        'profile_picture': profile_picture_url,
                        'onboarding_completed': onboarding_completed,
                    },
                    'tokens': {
                        'access': access_token,
                        'refresh': refresh_token,
                    }
                },
                status_code=status.HTTP_200_OK
            )
        
        # Return validation errors
        return standard_response(
            success=False,
            message="Login failed",
            errors=serializer.errors,
            status_code=status.HTTP_401_UNAUTHORIZED
        )


class UserLogoutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    """
    API endpoint for user logout
    
    POST /api/users/logout/
    
    Request body:
    {
        "refresh": "refresh_token_here"
    }
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Handle user logout by blacklisting refresh token"""
        try:
            refresh_token = request.data.get('refresh')
            
            if not refresh_token:
                return standard_response(
                    success=False,
                    message="Refresh token is required",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Blacklist the refresh token
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            return standard_response(
                success=True,
                message="Logout successful",
                status_code=status.HTTP_200_OK
            )
        
        except TokenError:
            return standard_response(
                success=False,
                message="Invalid or expired token",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return standard_response(
                success=False,
                message=f"Logout failed: {str(e)}",
                status_code=status.HTTP_400_BAD_REQUEST
            )


import logging

logger = logging.getLogger(__name__)

class FirebaseAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint for Firebase authentication (Google/Apple login)
    
    POST /api/users/firebase-auth/
    
    Request body:
    {
        "firebase_token": "firebase_id_token_from_client",
        "name": "John Doe" (optional),
        "date_of_birth": "1990-01-15" (optional)
    }
    """
    
    permission_classes = [AllowAny]
    serializer_class = FirebaseAuthSerializer
    
    def post(self, request):
        """Authenticate user with Firebase token"""
        logger.info(f"FirebaseAuthView POST request received. Headers: {request.headers}")
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            try:
                # Verify Firebase token
                firebase_token = serializer.validated_data['firebase_token']
                logger.info(f"Verifying Firebase token: {firebase_token[:30]}...")
                decoded_token = verify_firebase_token(firebase_token)
                logger.info(f"Firebase token verified successfully. Decoded token: {decoded_token}")
                
                # Extract user data from token and request
                firebase_uid = decoded_token.get('uid')
                email = decoded_token.get('email') or serializer.validated_data.get('email')
                raw_name = serializer.validated_data.get('name') or decoded_token.get('name')
                if raw_name:
                    name = raw_name
                elif email:
                    name = email.split('@')[0]
                else:
                    name = f"user_{firebase_uid[:8]}" if firebase_uid else "Closly User"
                
                # Determine auth provider
                firebase_provider = decoded_token.get('firebase', {}).get('sign_in_provider', 'google')
                auth_provider_map = {
                    'google.com': 'google',
                    'apple.com': 'apple',
                }
                auth_provider = auth_provider_map.get(firebase_provider, 'google')
                
                # Validate UID
                if not firebase_uid:
                    return standard_response(
                        success=False,
                        message="Invalid token: missing UID",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                # If new user and email is missing from both token and payload, require email
                if not email and not User.objects.filter(firebase_uid=firebase_uid).exists():
                    return standard_response(
                        success=False,
                        message="Email is required to complete registration with Closly.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                # Create or get user
                user = User.objects.create_firebase_user(
                    email=email,
                    name=name,
                    firebase_uid=firebase_uid,
                    auth_provider=auth_provider
                )
                
                # Update date of birth if provided
                dob = serializer.validated_data.get('date_of_birth')
                if dob and not user.date_of_birth:
                    user.date_of_birth = dob
                    user.save(update_fields=['date_of_birth'])
                
                # Generate JWT tokens
                refresh = RefreshToken.for_user(user)
                access_token = str(refresh.access_token)
                refresh_token = str(refresh)
                
                # Update last login
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                
                # Log login history
                UserLoginHistory.objects.create(
                    user=user,
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request),
                    auth_method=auth_provider
                )
                
                # Check onboarding completion status
                onboarding_completed = (
                    hasattr(user, 'preferences') and user.preferences.onboarding_completed
                ) or False

                profile_picture_url = request.build_absolute_uri(user.profile_picture.url) if user.profile_picture else None

                # Return success response
                return standard_response(
                    success=True,
                    message="Authentication successful",
                    data={
                        'user': {
                            'id': str(user.id),
                            'email': user.email,
                            'name': user.name,
                            'is_email_verified': user.is_email_verified,
                            'auth_provider': user.auth_provider,
                            'profile_picture': profile_picture_url,
                            'onboarding_completed': onboarding_completed,
                        },
                        'tokens': {
                            'access': access_token,
                            'refresh': refresh_token,
                        }
                    },
                    status_code=status.HTTP_200_OK
                )
            
            except Exception as e:
                logger.error(f"Firebase authentication failed: {str(e)}", exc_info=True)
                return standard_response(
                    success=False,
                    message=f"Firebase authentication failed: {str(e)}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        
        logger.error(f"FirebaseAuthView serializer errors: {serializer.errors}")
        return standard_response(
            success=False,
            message="Invalid request data",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
"""
API Views - Part 2: Email Verification, Password Management, Profile
"""


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to verify OTP for account activation
    """
    permission_classes = [AllowAny]
    serializer_class = VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            try:
                user = User.objects.get(email=email)
                if user.otp == otp and user.is_otp_valid():
                    user.is_active = True
                    user.is_email_verified = True
                    user.clear_otp()
                    user.save()
                    
                    # Send welcome email upon successful account verification
                    try:
                        send_welcome_email(user)
                    except Exception as e:
                        logger.error(f"Failed to send welcome email: {e}")
                        
                    return standard_response(success=True, message="OTP verified successfully. Your account is now active.")
                else:
                    # Expired OTP is automatically cleared from the DB by is_otp_valid()
                    return standard_response(success=False, message="Invalid or expired OTP.", status_code=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return standard_response(success=False, message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
        return standard_response(success=False, message="Invalid data.", errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to resend OTP with 30-second rate limiting
    """
    permission_classes = [AllowAny]
    serializer_class = ResendOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            try:
                user = User.objects.get(email=email)
                if not user.is_active:
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
                    
                    from .utils import generate_otp, send_otp_email
                    otp = generate_otp()
                    user.otp = otp
                    user.otp_created_at = timezone.now()
                    user.save(update_fields=['otp', 'otp_created_at'])
                    send_otp_email(user, otp)
                    return standard_response(success=True, message="OTP has been resent to your email.")
                else:
                    return standard_response(success=False, message="User is already active.", status_code=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return standard_response(success=False, message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
        return standard_response(success=False, message="Invalid data.", errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


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
                from .utils import generate_otp, send_password_reset_email
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


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]
    """
    API endpoint to get and update user profile
    
    GET /api/users/profile/ - Get user profile
    PUT /api/users/profile/ - Update full profile
    PATCH /api/users/profile/ - Partial update profile
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user profile"""
        user = request.user
        serializer = UserProfileSerializer(user, context={'request': request})
        
        return standard_response(
            success=True,
            message="Profile retrieved successfully",
            data=serializer.data,
            status_code=status.HTTP_200_OK
        )
    
    def put(self, request):
        """Update full user profile"""
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            
            # Return updated profile
            profile_serializer = UserProfileSerializer(user, context={'request': request})
            
            return standard_response(
                success=True,
                message="Profile updated successfully",
                data=profile_serializer.data,
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Profile update failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    def patch(self, request):
        """Partial update user profile"""
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            
            # Return updated profile
            profile_serializer = UserProfileSerializer(user, context={'request': request})
            
            return standard_response(
                success=True,
                message="Profile updated successfully",
                data=profile_serializer.data,
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Profile update failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    """
    API endpoint to delete user account
    
    DELETE /api/users/account-delete/
    
    Request body:
    {
        "password": "user_password",
        "confirm_deletion": true
    }
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDeleteSerializer
    
    def delete(self, request):
        """Delete user account"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = request.user
            password = serializer.validated_data['password']
            
            # Verify password (for email/password users)
            if user.auth_provider == 'email':
                if not user.check_password(password):
                    return standard_response(
                        success=False,
                        message="Incorrect password",
                        errors={'password': ['Incorrect password']},
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            
            # Store email for confirmation email
            user_email = user.email
            user_name = user.name
            
            # Send account deletion confirmation email before deleting
            try:
                send_account_deletion_email(user)
            except Exception:
                pass  # Continue with deletion even if email fails
            
            # Delete user account
            user.delete()
            
            return standard_response(
                success=True,
                message="Account deleted successfully",
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Account deletion failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom token refresh view with standard response format
    
    POST /api/users/token/refresh/
    
    Request body:
    {
        "refresh": "refresh_token_here"
    }
    """
    
    def post(self, request, *args, **kwargs):
        """Refresh access token"""
        try:
            response = super().post(request, *args, **kwargs)
            
            return standard_response(
                success=True,
                message="Token refreshed successfully",
                data=response.data,
                status_code=status.HTTP_200_OK
            )
        
        except TokenError as e:
            return standard_response(
                success=False,
                message="Token refresh failed",
                errors={'detail': str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        except InvalidToken as e:
            return standard_response(
                success=False,
                message="Invalid token",
                errors={'detail': str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED
            )


class CustomTokenVerifyView(TokenVerifyView):
    """
    Custom token verify view with standard response format
    
    POST /api/users/token/verify/
    
    Request body:
    {
        "token": "access_token_here"
    }
    """
    
    def post(self, request, *args, **kwargs):
        """Verify access token"""
        try:
            response = super().post(request, *args, **kwargs)
            
            return standard_response(
                success=True,
                message="Token is valid",
                data={'valid': True},
                status_code=status.HTTP_200_OK
            )
        
        except TokenError as e:
            return standard_response(
                success=False,
                message="Token is invalid or expired",
                data={'valid': False},
                errors={'detail': str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        except InvalidToken as e:
            return standard_response(
                success=False,
                message="Invalid token",
                data={'valid': False},
                errors={'detail': str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED
            )

class SetLanguageView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]
    serializer_class = LanguagePreferenceSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            language = serializer.validated_data['language']
            user = request.user
            user.preferred_language = language
            user.save(update_fields=['preferred_language'])
            return standard_response(success=True, message="Language preference updated successfully.", data={'language': language})
        return standard_response(success=False, message="Invalid request data", errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)



# ======================================================================
# USER PREFERENCE VIEW
# ======================================================================

from .models import UserPreference
from .serializers import UserPreferenceSerializer


class UserPreferenceView(APIView):
    """
    GET  /api/users/preferences/
        Returns the current user's preferences + all valid choice options
        so the frontend can render the onboarding UI dynamically.

    POST /api/users/preferences/
        Save/update preferences. All fields are optional — submit any
        subset. Designed to support saving one page at a time.

    Example POST body (all fields optional, submit only what you have):
    {
        "style_match": ["minimalist", "classic"],
        "body_type": "hourglass",
        "height_cm": 165,
        "weight_kg": 60,
        "chest": "36 inches",
        "waist": "30 inches",
        "hip": "38 inches",
        "body_size": "m",
        "shoe_size": "UK 8",

        "skin_tone": "#F0B27A",
        "color_palette": "neutral_minimalist",
        "clothing_categories": {
            "tops": ["shirts", "hoodies"],
            "shoes": ["sneakers", "boots"]
        },
        "preferred_brands": ["zara", "nike", "uniqlo"]
    }
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]

    def get(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(prefs)
        return Response({
            'success': True,
            'message': 'Preferences retrieved successfully.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        # partial=True means ALL fields are optional on every call
        serializer = UserPreferenceSerializer(prefs, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Preferences saved successfully.',
                'data': serializer.data,
            }, status=status.HTTP_200_OK)
        return Response({
            'success': False,
            'message': 'Invalid preference data.',
            'errors': serializer.errors,
        }, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        """Update onboarding preferences (full/partial update)"""
        return self.post(request)

    def patch(self, request):
        """Partial update onboarding preferences"""
        return self.post(request)
