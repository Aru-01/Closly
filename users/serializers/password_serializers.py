from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.validators import (
    validate_password_strength,
    validate_password_match,
)

User = get_user_model()


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
            pass
        return value


class PasswordResetOTPVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying OTP for password reset
    """
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=4)


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
        try:
            validate_password_match(attrs['new_password'], attrs['confirm_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'confirm_password': str(e)})
        
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({
                'new_password': 'New password must be different from old password.'
            })
        return attrs
