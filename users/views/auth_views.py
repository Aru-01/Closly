import logging
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from users.models import UserLoginHistory
from users.serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    FirebaseAuthSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
)
from users.utils import (
    verify_firebase_token,
    send_welcome_email,
    get_client_ip,
    get_user_agent,
    build_absolute_media_url,
)
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

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

            profile_picture_url = build_absolute_media_url(user.profile_picture, request=request)

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

                profile_picture_url = build_absolute_media_url(user.profile_picture, request=request)

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
                    
                    from users.utils import generate_otp, send_otp_email
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
        
        except (TokenError, InvalidToken) as e:
            return standard_response(
                success=False,
                message="Token refresh failed",
                errors={'detail': str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        except User.DoesNotExist:
            return standard_response(
                success=False,
                message="User account associated with this token was not found or has been deleted. Please log in again.",
                errors={'detail': "User not found. Please log in again."},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")
            return standard_response(
                success=False,
                message="Token refresh failed. Please log in again.",
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

