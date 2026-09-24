from django.utils import timezone
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
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
    
    class Meta:
        model = User
        fields = ['name', 'email', 'date_of_birth', 'gender', 'password', 'confirm_password', 'referral_code']
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
        """Validate date of birth"""
        try:
            validate_date_of_birth(value)
            
            # Additional age validation
            if not validate_age(value, min_age=13):
                raise serializers.ValidationError(
                    "You must be at least 13 years old to register."
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
        """Validate that passwords match"""
        try:
            validate_password_match(attrs['password'], attrs['confirm_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'confirm_password': str(e)})
        
        return attrs
    
    def create(self, validated_data):
        """Create new user or update unverified user and send OTP"""
        validated_data.pop('confirm_password')
        referral_code = validated_data.pop('referral_code', None)
        unverified_user = self.context.get('unverified_existing_user')
        
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
            user.save()
        else:
            user = User.objects.create_user(
                email=validated_data['email'],
                name=validated_data['name'],
                password=validated_data['password'],
                date_of_birth=validated_data.get('date_of_birth'),
                gender=validated_data.get('gender'),
                is_active=False  # User is inactive until OTP verification
            )
        
        # If referral code provided, reward the referring user with 200 points
        if referral_code:
            ref_clean = referral_code.strip().upper()
            referrer = User.objects.filter(referral_code=ref_clean).first()
            if referrer and referrer.id != user.id:
                try:
                    from rewards.services import award_points
                    award_points(
                        user=referrer,
                        action_type='invite_friend',
                        description=f"Invited friend {user.name or user.email}",
                        reference_id=str(user.id)
                    )
                except Exception:
                    pass

        # Generate and send OTP
        from users.utils import generate_otp, send_otp_email
        otp = generate_otp()
        user.otp = otp
        user.otp_created_at = timezone.now()
        user.save(update_fields=['otp', 'otp_created_at'])
        send_otp_email(user, otp)
        
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
        """Validate user credentials"""
        email = attrs.get('email', '').lower()
        password = attrs.get('password')
        
        if email and password:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise InvalidCredentialsException("Invalid email or password")
            
            if not user.is_active:
                raise serializers.ValidationError("User account is disabled.")
            
            user = authenticate(email=email, password=password)
            if not user:
                raise InvalidCredentialsException("Invalid email or password")
            
            attrs['user'] = user
            return attrs
        else:
            raise serializers.ValidationError("Must include 'email' and 'password'.")


class FirebaseAuthSerializer(serializers.Serializer):
    """
    Serializer for Firebase authentication (Google/Apple login)
    
    Required fields:
    - firebase_token: Firebase ID token from client
    """
    
    firebase_token = serializers.CharField(
        required=True,
        write_only=True,
        help_text="Firebase ID token obtained from client-side Firebase authentication"
    )
    
    # Optional fields for additional user data
    name = serializers.CharField(
        required=False,
        help_text="User's full name (optional, will use Firebase data if not provided)"
    )
    
    email = serializers.EmailField(
        required=False,
        help_text="User's email address (optional, fallback if not provided in Firebase token)"
    )
    
    date_of_birth = serializers.DateField(
        required=False,
        help_text="User's date of birth (optional)"
    )


class VerifyOTPSerializer(serializers.Serializer):
    """
    Serializer for OTP verification
    """
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=4)


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
