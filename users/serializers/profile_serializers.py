from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.models import UserPreference
from users.validators import (
    validate_name,
    validate_date_of_birth,
    validate_profile_picture,
)
from users.utils import validate_age, build_absolute_media_url
from rewards.serializers import (
    RewardPointTransactionSerializer,
    UserRewardProfileSerializer,
)

User = get_user_model()


class EmailVerificationSerializer(serializers.Serializer):
    """
    Serializer for email verification
    """
    token = serializers.CharField(
        required=True,
        help_text="Email verification token sent to user's email"
    )


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
    
    share_url = serializers.SerializerMethodField(
        help_text="Shareable public profile URL"
    )

    points_summary = serializers.SerializerMethodField(
        help_text="Current points balance and tier status"
    )

    followers_count = serializers.SerializerMethodField(
        help_text="Total number of users following this user"
    )

    following_count = serializers.SerializerMethodField(
        help_text="Total number of users this user is following"
    )

    looks_count = serializers.SerializerMethodField(
        help_text="Total number of outfit looks created by user"
    )

    outfit_count = serializers.SerializerMethodField(
        help_text="Alias for looks_count matching other user profile response"
    )

    outfits_count = serializers.SerializerMethodField(
        help_text="Plural alias for looks_count"
    )

    closet_count = serializers.SerializerMethodField(
        help_text="Total number of wardrobe items in digital closet"
    )

    style_dna = serializers.SerializerMethodField(
        help_text="User's style DNA preferences (e.g. ['minimalist', 'nordic'])"
    )

    style_match = serializers.SerializerMethodField(
        help_text="List of user's style match keys"
    )

    current_tier = serializers.SerializerMethodField(
        help_text="User's current reward loyalty tier (e.g. Bronze, Silver, Gold, Platinum, Diamond)"
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
            'city',
            'age',
            'bio',
            'profile_picture',
            'auth_provider',
            'is_email_verified',
            'is_subscribed',
            'onboarding_completed',
            'referral_code',
            'share_url',
            'points_summary',
            'current_tier',
            'followers_count',
            'following_count',
            'looks_count',
            'outfit_count',
            'outfits_count',
            'closet_count',
            'style_dna',
            'style_match',
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
            'referral_code',
            'share_url',
            'points_summary',
            'current_tier',
            'followers_count',
            'following_count',
            'looks_count',
            'outfit_count',
            'outfits_count',
            'closet_count',
            'style_dna',
            'style_match',
            'date_joined',
            'last_login',
        ]
    
    profile_picture = serializers.SerializerMethodField(
        help_text="Full absolute URL of user's profile picture"
    )

    def get_age(self, obj):
        """Calculate age from date of birth"""
        from users.utils import calculate_age
        return calculate_age(obj.date_of_birth)

    def get_onboarding_completed(self, obj):
        """Check if user has completed onboarding preferences"""
        return obj.preferences.onboarding_completed if hasattr(obj, 'preferences') else False

    def get_profile_picture(self, obj):
        """Build full absolute URL for profile picture"""
        if not obj.profile_picture:
            return None
        return build_absolute_media_url(obj.profile_picture, request=self.context.get('request'))

    def get_share_url(self, obj):
        """Build full public profile share URL using email handle"""
        handle = obj.email.split('@')[0] if obj.email and '@' in obj.email else str(obj.id)
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(f"/u/{handle}/")
        return f"https://closly.app/u/{handle}/"

    def get_points_summary(self, obj):
        """Get points balance and tier info"""
        from rewards.services import get_tier_info, process_expired_points
        process_expired_points(obj)
        reward_profile = getattr(obj, 'reward_profile', None)
        available = reward_profile.available_points if reward_profile else 0
        lifetime = reward_profile.lifetime_points if reward_profile else 0
        tier_info = get_tier_info(lifetime)
        return {
            'available_points': available,
            'lifetime_points': lifetime,
            'total_points': available,
            **tier_info
        }

    def get_followers_count(self, obj):
        """Total followers count"""
        if hasattr(obj, '_cached_followers_count'):
            return obj._cached_followers_count
        try:
            val = obj.followers_set.count()
        except Exception:
            val = 0
        obj._cached_followers_count = val
        return val

    def get_following_count(self, obj):
        """Total following count"""
        if hasattr(obj, '_cached_following_count'):
            return obj._cached_following_count
        try:
            val = obj.following_set.count()
        except Exception:
            val = 0
        obj._cached_following_count = val
        return val

    def get_looks_count(self, obj):
        """Total outfit looks created by user"""
        if hasattr(obj, '_cached_looks_count'):
            return obj._cached_looks_count
        try:
            val = obj.today_outfits.count()
        except Exception:
            val = 0
        obj._cached_looks_count = val
        return val

    def get_outfit_count(self, obj):
        """Alias for looks_count matching other user profile response"""
        return self.get_looks_count(obj)

    def get_outfits_count(self, obj):
        """Plural alias for looks_count"""
        return self.get_looks_count(obj)

    def get_closet_count(self, obj):
        """Total items in user's digital wardrobe"""
        if hasattr(obj, '_cached_closet_count'):
            return obj._cached_closet_count
        try:
            val = obj.closet_items.count()
        except Exception:
            val = 0
        obj._cached_closet_count = val
        return val

    def get_style_dna(self, obj):
        """User's style DNA identities (e.g. ['minimalist', 'nordic'])"""
        try:
            if hasattr(obj, 'preferences') and obj.preferences:
                return obj.preferences.style_match or []
        except Exception:
            pass
        return []

    def get_style_match(self, obj):
        """Alias for style_dna"""
        return self.get_style_dna(obj)

    def get_current_tier(self, obj):
        """User's loyalty tier name"""
        try:
            reward_profile = getattr(obj, 'reward_profile', None)
            return reward_profile.current_tier if reward_profile else 'Bronze'
        except Exception:
            return 'Bronze'

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
                raise serializers.ValidationError("You must be at least 13 years old.")
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
        fields = ['name', 'date_of_birth', 'gender', 'occupation', 'country', 'city', 'bio', 'profile_picture']
    
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
                raise serializers.ValidationError("You must be at least 13 years old.")
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
        help_text="User's password for verification"
    )
    confirm = serializers.BooleanField(
        required=True,
        help_text="Must be true to confirm deletion"
    )
    
    def validate_confirm(self, value):
        """Ensure user confirms deletion"""
        if not value:
            raise serializers.ValidationError(
                "You must confirm that you want to delete your account."
            )
        return value


class LanguagePreferenceSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=[('en', 'English'), ('hi', 'Hindi'), ('pt', 'Portuguese')])


class UserPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for reading and writing user onboarding preferences.
    """
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


# Backward-compatibility aliases
ClosetPointTransactionSerializer = RewardPointTransactionSerializer
UserPointSummarySerializer = UserRewardProfileSerializer
