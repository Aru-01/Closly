import logging
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from users.models import UserLoginHistory
from users.serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    FirebaseAuthSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
)
import secrets
from users.utils import (
    verify_firebase_token,
    send_welcome_email,
    get_client_ip,
    get_user_agent,
    build_absolute_media_url,
    set_user_online,
    set_user_offline,
)
from users.utils.common_utils import (
    get_truncated_ip,
    get_minimized_user_agent,
    record_user_consent,
)
from users.throttling import (
    LoginRateThrottle,
    OTPVerifyRateThrottle,
    OTPResendRateThrottle,
)
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

@extend_schema(
    tags=["Authentication & Security"],
    summary="User Registration / Signup",
    description="Register a new user account with email, password, and optional referral code. Dispatches a 4-digit activation OTP to user's email.",
    request=UserRegistrationSerializer,
    responses={
        201: OpenApiResponse(description="Registration successful, OTP dispatched to email"),
        400: OpenApiResponse(description="Validation error or duplicate email"),
    }
)
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
        serializer = self.serializer_class(data=request.data, context={'request': request})
        
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
        
        code = "BAD_REQUEST"
        if 'invite_code' in serializer.errors:
            err_msg = str(serializer.errors['invite_code'])
            if 'required' in err_msg.lower():
                code = "INVITE_REQUIRED"
            else:
                code = "INVALID_INVITE"
        elif 'date_of_birth' in serializer.errors:
            err_msg = str(serializer.errors['date_of_birth'])
            if 'years old' in err_msg.lower() or 'underage' in err_msg.lower():
                code = "UNDERAGE"

        return standard_response(
            success=False,
            message="Registration failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code
        )


@extend_schema(
    tags=["Authentication & Security"],
    summary="Email & Password Login",
    description="Authenticate with registered email and password. Returns JWT access and refresh tokens, user profile metadata, and onboarding status.",
    request=UserLoginSerializer,
    responses={
        200: OpenApiResponse(description="Login successful with JWT access & refresh tokens"),
        401: OpenApiResponse(description="Invalid credentials or inactive account"),
    }
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
    throttle_classes = [LoginRateThrottle]
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
            
            # Log login history with truncated IP and minimized UA (U-25)
            UserLoginHistory.objects.create(
                user=user,
                ip_address=get_truncated_ip(get_client_ip(request)),
                user_agent=get_minimized_user_agent(get_user_agent(request)),
                auth_method='email'
            )
            
            # Check onboarding completion status
            onboarding_completed = (
                hasattr(user, 'preferences') and user.preferences.onboarding_completed
            ) or False

            profile_picture_url = build_absolute_media_url(user.profile_picture, request=request)
            set_user_online(str(user.id))

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
                        'is_online': True,
                        'last_seen': timezone.now().isoformat(),
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


@extend_schema(
    tags=["Authentication & Security"],
    summary="User Logout",
    description="Invalidates and blacklists the provided JWT refresh token to securely terminate the session.",
    responses={
        200: OpenApiResponse(description="Logout successful, refresh token blacklisted"),
        400: OpenApiResponse(description="Invalid or expired token"),
    }
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
            if request.user and request.user.is_authenticated:
                set_user_offline(str(request.user.id))
            
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

@extend_schema(
    tags=["Authentication & Security"],
    summary="Firebase Social Login (Google / Apple)",
    description="Authenticate or register user using a Firebase ID token. Generates Closly JWT access and refresh tokens.",
    request=FirebaseAuthSerializer,
    responses={
        200: OpenApiResponse(description="Authentication successful with JWT tokens"),
        400: OpenApiResponse(description="Invalid Firebase token or missing email"),
    }
)
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
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            try:
                # Verify Firebase token
                firebase_token = serializer.validated_data['firebase_token']
                decoded_token = verify_firebase_token(firebase_token)
                
                # Extract user data strictly from token (U-02)
                firebase_uid = decoded_token.get('uid')
                email = decoded_token.get('email')
                email_verified = decoded_token.get('email_verified', False)

                # Validate UID, email and email_verified
                if not firebase_uid:
                    return standard_response(
                        success=False,
                        message="Invalid token: missing UID",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )

                if not email or not email_verified:
                    return standard_response(
                        success=False,
                        message="Firebase identity provider must provide a verified email address.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )

                # Determine auth provider with strict allowlist
                firebase_provider = decoded_token.get('firebase', {}).get('sign_in_provider')
                auth_provider_map = {
                    'google.com': 'google',
                    'apple.com': 'apple',
                }
                if firebase_provider not in auth_provider_map:
                    return standard_response(
                        success=False,
                        message="Unsupported authentication provider. Only Google and Apple are permitted.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                auth_provider = auth_provider_map[firebase_provider]
                # Determine if user is new for invite gate and consent (U-08, U-21)
                is_new_user = not User.objects.filter(firebase_uid=firebase_uid).exists() and not User.objects.filter(email__iexact=email).exists()

                # Enforce invite gating on new registrations if invite mode is enabled (U-08)
                registration_mode = getattr(settings, 'MYC_REGISTRATION_MODE', 'open')
                invite_code = (serializer.validated_data.get('invite_code') or '').strip().upper()
                valid_invite = None
                if is_new_user and registration_mode == 'invite':
                    if not invite_code:
                        return standard_response(
                            success=False,
                            message="An invite code is required to register.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                            code="INVITE_REQUIRED"
                        )
                    bypass_codes = [c.strip().upper() for c in getattr(settings, 'MYC_INVITE_BYPASS_CODES', '').split(',') if c.strip()]
                    if invite_code not in bypass_codes:
                        from users.models import Invite
                        invite = Invite.objects.filter(code=invite_code).first()
                        if not invite or not invite.is_valid():
                            return standard_response(
                                success=False,
                                message="Invalid or expired invite code.",
                                status_code=status.HTTP_400_BAD_REQUEST,
                                code="INVALID_INVITE"
                            )
                        valid_invite = invite

                raw_name = serializer.validated_data.get('name') or decoded_token.get('name')
                if raw_name:
                    name = raw_name
                elif email:
                    name = email.split('@')[0]
                else:
                    name = f"user_{firebase_uid[:8]}"
                
                # Validate date of birth against 16+ age gate (U-10)
                dob = serializer.validated_data.get('date_of_birth')
                min_age = getattr(settings, 'MYC_MIN_AGE', 16)
                if dob:
                    from users.utils import validate_age
                    if not validate_age(dob, min_age=min_age):
                        return standard_response(
                            success=False,
                            message=f"You must be at least {min_age} years old to register.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                            code="UNDERAGE"
                        )

                # Extract avatar URL strictly from token picture claim (U-07)
                photo_url = decoded_token.get('picture')

                # Create or get user atomically with invite consumption and consent recording (U-08, U-21)
                with transaction.atomic():
                    user = User.objects.create_firebase_user(
                        email=email,
                        name=name,
                        firebase_uid=firebase_uid,
                        auth_provider=auth_provider,
                        photo_url=photo_url,
                        email_verified=True
                    )
                    
                    if is_new_user:
                        if valid_invite:
                            valid_invite.used_by = user
                            valid_invite.used_at = timezone.now()
                            valid_invite.save(update_fields=['used_by', 'used_at'])
                        
                        record_user_consent(user, 'tos_privacy', granted=True, request=request)
                    
                    # Update date of birth if provided
                    if dob and not user.date_of_birth:
                        user.date_of_birth = dob
                        user.save(update_fields=['date_of_birth'])
                
                # Validate user active state before issuing tokens (U-22)
                if not user.is_active:
                    return standard_response(
                        success=False,
                        message="User account is disabled.",
                        status_code=status.HTTP_403_FORBIDDEN,
                        code="ACCOUNT_DISABLED"
                    )

                # Generate JWT tokens
                refresh = RefreshToken.for_user(user)
                access_token = str(refresh.access_token)
                refresh_token = str(refresh)
                
                # Update last login
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                
                # Log login history with truncated IP and minimized UA (U-25)
                UserLoginHistory.objects.create(
                    user=user,
                    ip_address=get_truncated_ip(get_client_ip(request)),
                    user_agent=get_minimized_user_agent(get_user_agent(request)),
                    auth_method=auth_provider
                )
                
                # Check onboarding completion status
                onboarding_completed = (
                    hasattr(user, 'preferences') and user.preferences.onboarding_completed
                ) or False

                user.refresh_from_db()
                profile_picture_url = build_absolute_media_url(user.profile_picture, request=request)
                set_user_online(str(user.id))

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
                            'is_online': True,
                            'last_seen': timezone.now().isoformat(),
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


@extend_schema(
    tags=["Authentication & Security"],
    summary="Verify Registration OTP",
    description="Verify 4-digit OTP sent to email during registration to activate the user account.",
    request=VerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="OTP verified successfully, account activated"),
        400: OpenApiResponse(description="Invalid or expired OTP"),
        404: OpenApiResponse(description="User not found"),
    }
)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to verify OTP for account activation
    """
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyRateThrottle]
    serializer_class = VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            
            from users.throttling import check_lockout, record_failed_attempt, clear_failed_attempts
            if check_lockout(email, scope='otp'):
                return standard_response(
                    success=False,
                    message="Too many failed attempts. This account is locked for 15 minutes.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            try:
                user = User.objects.get(email=email)
                # Constant-time comparison
                if user.otp and secrets.compare_digest(str(user.otp), str(otp)) and user.is_otp_valid():
                    user.is_active = True
                    user.is_email_verified = True
                    user.clear_otp()
                    user.save()
                    clear_failed_attempts(email, scope='otp')
                    
                    # Award deferred referral points if user was invited (U-09)
                    if getattr(user, 'referred_by', None):
                        try:
                            from rewards.services import activate_referral_reward
                            activate_referral_reward(user)
                        except Exception as e:
                            logger.warning(f"Deferred referral points award error: {e}")

                    # Send welcome email upon successful account verification
                    try:
                        send_welcome_email(user)
                    except Exception as e:
                        logger.error(f"Failed to send welcome email: {e}")
                        
                    return standard_response(
                        success=True,
                        message="OTP verified successfully. Your account is now active.",
                        code="OTP_VERIFIED"
                    )
                else:
                    record_failed_attempt(email, scope='otp')
                    return standard_response(
                        success=False,
                        message="Invalid email or verification code.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                        code="INVALID_OTP"
                    )
            except User.DoesNotExist:
                # Anti-enumeration (U-12): Uniform response preventing user enumeration
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
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR"
        )

@extend_schema(
    tags=["Authentication & Security"],
    summary="Resend Registration OTP",
    description="Resends a fresh 6-digit activation OTP to the specified email address (throttled to once per 2 minutes).",
    request=ResendOTPSerializer,
    responses={
        200: OpenApiResponse(description="OTP resent to email"),
        400: OpenApiResponse(description="Account already active or invalid data"),
        404: OpenApiResponse(description="User not found"),
        429: OpenApiResponse(description="Rate limit exceeded, retry after cooldown"),
    }
)
class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    API endpoint to resend OTP with 2-minute rate limiting
    """
    permission_classes = [AllowAny]
    throttle_classes = [OTPResendRateThrottle]
    serializer_class = ResendOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            from users.throttling import check_lockout
            if check_lockout(email, scope='otp'):
                return standard_response(
                    success=False,
                    message="Too many failed attempts. This account is locked for 15 minutes.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="ACCOUNT_LOCKED"
                )
            try:
                user = User.objects.get(email=email)
                if not user.is_active:
                    # 2-minute (120-second) rate limiting check
                    if user.otp_created_at:
                        seconds_passed = (timezone.now() - user.otp_created_at).total_seconds()
                        if seconds_passed < 120:
                            retry_after = int(120 - seconds_passed)
                            return standard_response(
                                success=False,
                                message=f"Please wait {retry_after} seconds before requesting another OTP.",
                                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                code="RATE_LIMITED"
                            )
                    
                    from users.utils import generate_otp, send_otp_email
                    otp = generate_otp(6)
                    user.otp = otp
                    user.otp_created_at = timezone.now()
                    user.save(update_fields=['otp', 'otp_created_at'])
                    send_otp_email(user, otp)
                    return standard_response(
                        success=True,
                        message="If an account exists with that email and requires verification, a verification code has been sent.",
                        code="OTP_SENT"
                    )
                else:
                    # Anti-enumeration (U-12): Uniform response for already active accounts
                    return standard_response(
                        success=True,
                        message="If an account exists with that email and requires verification, a verification code has been sent.",
                        code="OTP_SENT"
                    )
            except User.DoesNotExist:
                # Anti-enumeration (U-12): Uniform response for nonexistent accounts
                return standard_response(
                    success=True,
                    message="If an account exists with that email and requires verification, a verification code has been sent.",
                    code="OTP_SENT"
                )
        return standard_response(
            success=False,
            message="Invalid data.",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR"
        )



@extend_schema(
    tags=["Authentication & Security"],
    summary="Refresh JWT Access Token",
    description="Exchange a valid JWT refresh token for a new access token.",
    responses={
        200: OpenApiResponse(description="Token refreshed successfully"),
        401: OpenApiResponse(description="Invalid or expired refresh token"),
    }
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


@extend_schema(
    tags=["Authentication & Security"],
    summary="Verify JWT Token",
    description="Verify if a given JWT access token is valid and unexpired.",
    responses={
        200: OpenApiResponse(description="Token is valid"),
        401: OpenApiResponse(description="Token is invalid or expired"),
    }
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

