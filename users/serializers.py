"""
API Serializers for user authentication and profile management
All serializers follow standard response format for consistency
"""

from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .validators import (
    validate_password_strength,
    validate_email_format,
    validate_name,
    validate_date_of_birth,
    validate_password_match,
    validate_profile_picture
)
from .exceptions import (
    InvalidCredentialsException,
    EmailNotVerifiedException,
    PasswordMismatchException,
    EmailAlreadyExistsException,
)
from .utils import validate_age

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
    
    class Meta:
        model = User
        fields = ['name', 'email', 'date_of_birth', 'gender', 'password', 'confirm_password']
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
        
        # Generate and send OTP
        from .utils import generate_otp, send_otp_email
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
            # Check if user exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise InvalidCredentialsException("Invalid email or password")
            
            # Check if user is active
            if not user.is_active:
                raise serializers.ValidationError("User account is disabled.")
            
            # Authenticate user
            user = authenticate(email=email, password=password)
            
            if not user:
                raise InvalidCredentialsException("Invalid email or password")
            
            # Check if email is verified (optional - uncomment if you want to enforce)
            # if not user.is_email_verified:
            #     raise EmailNotVerifiedException()
            
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


class EmailVerificationSerializer(serializers.Serializer):
    """
    Serializer for email verification
    """
    
    token = serializers.CharField(
        required=True,
        help_text="Email verification token sent to user's email"
    )


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Serializer for requesting password reset
    """
    
    email = serializers.EmailField(
        required=True,
        help_text="Email address of the account to reset password"
    )
    
    def validate_email(self, value):
        """Check if user with this email exists"""
        value = value.lower()
        
        if not User.objects.filter(email=value).exists():
            # For security, don't reveal if email exists or not
            # Just return the value, handle silently in view
            pass
        
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Serializer for confirming password reset with OTP
    """
    
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="New password"
    )
    
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Password confirmation"
    )
    
    def validate_password(self, value):
        """Validate password strength"""
        try:
            validate_password_strength(value)
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


class PasswordChangeSerializer(serializers.Serializer):
    """
    Serializer for changing password (authenticated user)
    """
    
    old_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Current password"
    )
    
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="New password"
    )
    
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="New password confirmation"
    )
    
    def validate_new_password(self, value):
        """Validate new password strength"""
        try:
            validate_password_strength(value)
            django_validate_password(value)
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
    
    def validate(self, attrs):
        """Validate passwords"""
        # Check if new passwords match
        try:
            validate_password_match(attrs['new_password'], attrs['confirm_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'confirm_password': str(e)})
        
        # Check if new password is different from old password
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({
                'new_password': 'New password must be different from old password.'
            })
        
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for user profile (read and update)
    """
    
    age = serializers.SerializerMethodField(
        read_only=True,
        help_text="User's age calculated from date of birth"
    )

    onboarding_completed = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether user has completed onboarding preferences"
    )
    
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'name',
            'date_of_birth',
            'gender',
            'occupation',
            'country',
            'age',
            'bio',
            'profile_picture',
            'auth_provider',
            'is_email_verified',
            'is_subscribed',
            'onboarding_completed',
            'date_joined',
            'last_login',
        ]
        read_only_fields = [
            'id',
            'email',
            'auth_provider',
            'is_email_verified',
            'is_subscribed',
            'onboarding_completed',
            'date_joined',
            'last_login',
        ]
    
    profile_picture = serializers.SerializerMethodField(
        help_text="Full absolute URL of user's profile picture"
    )

    def get_age(self, obj):
        """Calculate age from date of birth"""
        from .utils import calculate_age
        return calculate_age(obj.date_of_birth)

    def get_onboarding_completed(self, obj):
        """Check if user has completed onboarding preferences"""
        return obj.preferences.onboarding_completed if hasattr(obj, 'preferences') else False

    def get_profile_picture(self, obj):
        """Build full absolute URL for profile picture"""
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(obj.profile_picture.url)
        return obj.profile_picture.url

    # Mood tracking removed from the project. Any mood-related data/relations
    # have been intentionally omitted from the serializer.
    
    def validate_name(self, value):
        """Validate name"""
        try:
            validate_name(value)
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_date_of_birth(self, value):
        """Validate date of birth"""
        try:
            validate_date_of_birth(value)
            
            if not validate_age(value, min_age=13):
                raise serializers.ValidationError(
                    "You must be at least 13 years old."
                )
            
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_profile_picture(self, value):
        """Validate profile picture"""
        if value:
            try:
                validate_profile_picture(value)
                return value
            except DjangoValidationError as e:
                raise serializers.ValidationError(str(e))
        return value


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile (partial updates allowed)
    """
    
    class Meta:
        model = User
        fields = ['name', 'date_of_birth', 'gender', 'occupation', 'country', 'bio', 'profile_picture']
    
    def validate_name(self, value):
        """Validate name"""
        try:
            validate_name(value)
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_date_of_birth(self, value):
        """Validate date of birth"""
        try:
            validate_date_of_birth(value)
            
            if not validate_age(value, min_age=13):
                raise serializers.ValidationError(
                    "You must be at least 13 years old."
                )
            
            return value
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
    
    def validate_profile_picture(self, value):
        """Validate profile picture"""
        if value:
            try:
                validate_profile_picture(value)
                return value
            except DjangoValidationError as e:
                raise serializers.ValidationError(str(e))
        return value


class AccountDeleteSerializer(serializers.Serializer):
    """
    Serializer for account deletion confirmation
    """
    
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Enter your password to confirm account deletion"
    )
    
    confirm_deletion = serializers.BooleanField(
        required=True,
        help_text="Must be set to true to confirm deletion"
    )
    
    def validate_confirm_deletion(self, value):
        """Ensure user confirms deletion"""
        if not value:
            raise serializers.ValidationError(
                "You must confirm that you want to delete your account."
            )
        return value


class TokenRefreshResponseSerializer(serializers.Serializer):
    """
    Serializer for token refresh response
    """
    access = serializers.CharField(help_text="New access token")
    refresh = serializers.CharField(help_text="New refresh token (if rotation enabled)")


class VerifyOTPSerializer(serializers.Serializer):
    """
    Serializer for OTP verification
    """
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=4)

class PasswordResetOTPVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying OTP for password reset
    """
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=4)

class ResendOTPSerializer(serializers.Serializer):
    """
    Serializer for resending OTP
    """
    email = serializers.EmailField()

class TokenVerifyResponseSerializer(serializers.Serializer):
    """
    Serializer for token verification response
    """
    valid = serializers.BooleanField(help_text="Whether token is valid")
    user_id = serializers.UUIDField(help_text="User ID from token", required=False)

class LanguagePreferenceSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=[('en', 'English'), ('hi', 'Hindi'), ('pt', 'Portuguese')])


# ======================================================================
# USER PREFERENCE SERIALIZER
# ======================================================================

from .models import UserPreference


class UserPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for reading and writing user onboarding preferences.
    """

    # Read-only choice metadata (sent to frontend for rendering UI)
    style_match_options = serializers.SerializerMethodField(read_only=True)
    dress_for_options = serializers.SerializerMethodField(read_only=True)
    body_size_options = serializers.SerializerMethodField(read_only=True)
    skin_tone_options = serializers.SerializerMethodField(read_only=True)
    clothing_category_options = serializers.SerializerMethodField(read_only=True)
    brand_options = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UserPreference
        fields = [
            'style_match',
            'what_do_you_dress_for',
            'body_type',
            'height_cm',
            'weight_kg',
            'chest',
            'waist',
            'hip',
            'body_size',
            'shoe_size',
            'skin_tone',
            'color_palette',
            'clothing_categories',
            'preferred_brands',
            'onboarding_completed',
            'created_at',
            'updated_at',
            # Frontend helpers (read-only)
            'style_match_options',
            'dress_for_options',
            'body_size_options',
            'skin_tone_options',
            'clothing_category_options',
            'brand_options',
        ]
        read_only_fields = [
            'onboarding_completed',
            'created_at',
            'updated_at',
            'style_match_options',
            'dress_for_options',
            'body_size_options',
            'skin_tone_options',
            'clothing_category_options',
            'brand_options',
        ]

    def get_style_match_options(self, obj):
        """Returns list of {key, label} for style match options."""
        return [
            {'key': key, 'label': label}
            for key, label in UserPreference.STYLE_MATCH_CHOICES
        ]

    def get_dress_for_options(self, obj):
        """Returns list of {key, label} for dress for options."""
        return [
            {'key': key, 'label': label}
            for key, label in UserPreference.DRESS_FOR_CHOICES
        ]

    def validate_what_do_you_dress_for(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list.")
        valid = [k for k, _ in UserPreference.DRESS_FOR_CHOICES]
        invalid = [v for v in value if v not in valid]
        if invalid:
            raise serializers.ValidationError(f"Invalid values: {invalid}. Valid options: {valid}")
        return value

    def get_body_size_options(self, obj):
        """Returns list of body size choices."""
        return [
            {'key': key, 'label': label}
            for key, label in UserPreference.BODY_SIZE_CHOICES
        ]

    def get_skin_tone_options(self, obj):
        """Returns list of {hex, label} for frontend color picker."""
        return [
            {'hex': hex_code, 'label': label}
            for hex_code, label in UserPreference.SKIN_TONE_CHOICES
        ]

    def get_clothing_category_options(self, obj):
        """Returns the full nested clothing category tree."""
        return UserPreference.CLOTHING_CATEGORY_OPTIONS

    def get_brand_options(self, obj):
        """Returns brand options grouped by tier."""
        return UserPreference.BRAND_OPTIONS

    def validate_style_match(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list.")
        valid = [k for k, _ in UserPreference.STYLE_MATCH_CHOICES]
        invalid = [v for v in value if v not in valid]
        if invalid:
            raise serializers.ValidationError(f"Invalid values: {invalid}. Valid: {valid}")
        return value

    def validate_body_size(self, value):
        if not value:
            return value
        valid = [k for k, _ in UserPreference.BODY_SIZE_CHOICES]
        if value not in valid:
            raise serializers.ValidationError(f"Invalid body size. Valid: {valid}")
        return value

    def validate_skin_tone(self, value):
        if not value:
            return value
        valid = [h for h, _ in UserPreference.SKIN_TONE_CHOICES]
        if value not in valid:
            raise serializers.ValidationError(
                f"Invalid skin tone. Valid hex codes: {valid}"
            )
        return value

    def validate_clothing_categories(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object/dict.")
        valid_cats = UserPreference.CLOTHING_CATEGORY_OPTIONS
        for cat_key, items in value.items():
            if cat_key not in valid_cats:
                raise serializers.ValidationError(
                    f"Unknown category '{cat_key}'. Valid: {list(valid_cats.keys())}"
                )
            if not isinstance(items, list):
                raise serializers.ValidationError(f"Items in '{cat_key}' must be a list.")
            invalid_items = [i for i in items if i not in valid_cats[cat_key]]
            if invalid_items:
                raise serializers.ValidationError(
                    f"Invalid items in '{cat_key}': {invalid_items}. "
                    f"Valid: {valid_cats[cat_key]}"
                )
        return value

    def validate_preferred_brands(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of brand name strings.")
        return [b.lower().strip() for b in value if isinstance(b, str)]

    def update(self, instance, validated_data):
        for field, val in validated_data.items():
            setattr(instance, field, val)
        instance.onboarding_completed = True
        instance.save()
        return instance
