from django.utils import timezone
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from users.validators import (
    validate_name,
    validate_email_format,
    validate_date_of_birth,
    validate_password_strength,
    validate_password_match,
)
from users.exceptions import InvalidCredentialsException
from users.utils import validate_age

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration (signup)
    
    Required fields:
    - name: User's full name
    - email: User's email address
    - date_of_birth: User's date of birth
    - password: User's password
    - confirm_password: Password confirmation
    """
    
    # Extra field for password confirmation (not in model)
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Password confirmation"
    )
    
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="User's password (min 8 chars, must include uppercase, lowercase, number, special char)"
    )

    referral_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Optional referral code of the inviter"
    )

    invite_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Invite code required when invite mode is active (U-08)"
    )
    
    class Meta:
        model = User
        fields = ['name', 'email', 'date_of_birth', 'gender', 'password', 'confirm_password', 'referral_code', 'invite_code']
        extra_kwargs = {
            'name': {'required': True},
            'email': {'required': True, 'validators': []},
            'date_of_birth': {'required': True},
        }
    
    def validate_name(self, value):
        """Validate user's name"""
        try:
            validate_name(value)
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_email(self, value):
        """Validate email format and check if it already exists and is verified"""
        # Validate email format
        try:
            validate_email_format(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
        
        email = value.lower()
        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            if existing_user.is_email_verified:
                raise serializers.ValidationError("An account with this email already exists and is verified. Please log in.")
            else:
                # Store unverified user in context so create() can refresh account & OTP
                self.context['unverified_existing_user'] = existing_user
        
        return email
    
    def validate_date_of_birth(self, value):
        """Validate date of birth with 16+ age gate (GDPR Art. 8 / U-10)"""
        try:
            validate_date_of_birth(value)
            
            from django.conf import settings
            min_age = getattr(settings, 'MYC_MIN_AGE', 16)
            if not validate_age(value, min_age=min_age):
                raise serializers.ValidationError(
                    f"You must be at least {min_age} years old to register."
                )
            
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_password(self, value):
        """Validate password strength"""
        try:
            # Use custom validator
            validate_password_strength(value)
            
            # Also use Django's built-in validators
            django_validate_password(value)
            
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
    
    def validate(self, attrs):
        """Validate that passwords match and invite code if invite mode is enabled (U-08)"""
        try:
            validate_password_match(attrs['password'], attrs['confirm_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'confirm_password': str(e)})
        
        from django.conf import settings
        registration_mode = getattr(settings, 'MYC_REGISTRATION_MODE', 'open')
        invite_code = attrs.get('invite_code', '').strip().upper()
        unverified_existing_user = self.context.get('unverified_existing_user')

        if registration_mode == 'invite' and not unverified_existing_user:
            if not invite_code:
                raise serializers.ValidationError({'invite_code': "An invite code is required to register."})

            bypass_codes = [c.strip().upper() for c in getattr(settings, 'MYC_INVITE_BYPASS_CODES', '').split(',') if c.strip()]
            if invite_code in bypass_codes:
                self.context['invite_bypass'] = True
            else:
                from users.models import Invite
                invite = Invite.objects.filter(code=invite_code).first()
                if not invite or not invite.is_valid():
                    raise serializers.ValidationError({'invite_code': "Invalid or expired invite code."})
                self.context['valid_invite'] = invite

        return attrs
    
    def create(self, validated_data):
        """Create new user or update unverified user and send OTP inside atomic transaction"""
        validated_data.pop('confirm_password')
        referral_code = validated_data.pop('referral_code', None)
        validated_data.pop('invite_code', None)
        unverified_user = self.context.get('unverified_existing_user')
        valid_invite = self.context.get('valid_invite')
        
        with transaction.atomic():
            if unverified_user:
                user = unverified_user
                user.name = validated_data['name']
                user.set_password(validated_data['password'])
                if 'date_of_birth' in validated_data:
                    user.date_of_birth = validated_data.get('date_of_birth')
                if 'gender' in validated_data:
                    user.gender = validated_data.get('gender')
                user.is_active = False
                user.is_email_verified = False
            else:
                user = User.objects.create_user(
                    email=validated_data['email'],
                    name=validated_data['name'],
                    password=validated_data['password'],
                    date_of_birth=validated_data.get('date_of_birth'),
                    gender=validated_data.get('gender'),
                    is_active=False  # User is inactive until OTP verification
                )
            
            # Consume valid invite atomically if invite gate applied (U-08)
            if valid_invite:
                valid_invite.used_by = user
                valid_invite.used_at = timezone.now()
                valid_invite.save(update_fields=['used_by', 'used_at'])

            # Record referred_by if referral code provided; create PENDING reward (U-09)
            if referral_code:
                ref_clean = referral_code.strip().upper()
                referrer = User.objects.filter(referral_code=ref_clean).first()
                if referrer and referrer.id != user.id:
                    user.referred_by = referrer
                    from rewards.services import record_pending_referral_reward
                    record_pending_referral_reward(referrer, user)

            # Record auditable GDPR consent for ToS & Privacy (U-21, Consent System)
            from users.utils.common_utils import record_user_consent
            record_user_consent(user, 'tos_privacy', granted=True, request=self.context.get('request'))

            # Generate 6-digit OTP
            from users.utils import generate_otp, send_otp_email
            otp = generate_otp(6)
            user.otp = otp
            user.otp_created_at = timezone.now()
            user.save()

            # Asynchronously dispatch OTP email after transaction commits (U-05/U-26)
            transaction.on_commit(lambda: send_otp_email(user, otp))
            
            return user


class UserLoginSerializer(serializers.Serializer):
    """
    Serializer for user login
    
    Required fields:
    - email: User's email address
    - password: User's password
    """
    
    email = serializers.EmailField(
        required=True,
        help_text="User's email address"
    )
    
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="User's password"
    )
    
    def validate(self, attrs):
        """Validate user credentials with anti-enumeration protection (U-12)"""
        email = attrs.get('email', '').lower()
        password = attrs.get('password')
        
        if email and password:
            user = authenticate(email=email, password=password)
            if not user or not user.is_active:
                raise InvalidCredentialsException("Invalid email or password")
            
            attrs['user'] = user
            return attrs
        else:
            raise serializers.ValidationError("Must include 'email' and 'password'.")


class FirebaseAuthSerializer(serializers.Serializer):
    """
    Serializer for Firebase authentication (Google/Apple login).
    Accepts 'firebase_token' or 'id_token'.
    Email and avatar are derived exclusively from the verified token (U-02, U-07).
    """
    firebase_token = serializers.CharField(
        required=False,
        write_only=True,
        help_text="Firebase ID token obtained from client-side Firebase authentication"
    )
    id_token = serializers.CharField(
        required=False,
        write_only=True,
        help_text="Alias for firebase_token"
    )
    name = serializers.CharField(
        required=False,
        help_text="User's full name (optional, will use Firebase data if not provided)"
    )
    date_of_birth = serializers.DateField(
        required=False,
        help_text="User's date of birth (required for new registrations under 16+ age gate, U-10)"
    )
    invite_code = serializers.CharField(
        required=False,
        write_only=True,
        allow_blank=True,
        help_text="Invite code required for first login when invite mode is active (U-08)"
    )

    def validate(self, attrs):
        token = attrs.get('firebase_token') or attrs.get('id_token')
        if not token:
            raise serializers.ValidationError({"firebase_token": "This field is required."})
        attrs['firebase_token'] = token
        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    """
    Serializer for OTP verification (6-digit numeric OTP)
    """
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    """
    Serializer for resending OTP
    """
    email = serializers.EmailField()


class TokenRefreshResponseSerializer(serializers.Serializer):
    """
    Serializer for token refresh response
    """
    access = serializers.CharField(help_text="New access token")
    refresh = serializers.CharField(help_text="New refresh token (if rotation enabled)")


class TokenVerifyResponseSerializer(serializers.Serializer):
    """
    Serializer for token verification response
    """
    valid = serializers.BooleanField(help_text="Whether token is valid")
    user_id = serializers.UUIDField(help_text="User ID from token", required=False)
