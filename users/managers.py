"""
Custom User Manager for creating users and superusers
"""

from django.contrib.auth.models import BaseUserManager
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom user manager where email is the unique identifier
    instead of username for authentication.
    """
    
    def create_user(self, email, name, password=None, **extra_fields):
        """
        Create and save a regular user with the given email, name and password.
        
        Args:
            email (str): User's email address
            name (str): User's full name
            password (str): User's password
            **extra_fields: Additional fields for user model
            
        Returns:
            User: Created user instance
            
        Raises:
            ValueError: If email or name is not provided
        """
        if not email:
            raise ValueError(_('The Email field must be set'))
        
        if not name:
            raise ValueError(_('The Name field must be set'))
        
        # Normalize email (lowercase domain part)
        email = self.normalize_email(email)
        
        # Set default values
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_email_verified', False)
        
        # Create user instance
        user = self.model(
            email=email,
            name=name,
            **extra_fields
        )
        
        # Set password (this will hash the password)
        if password:
            user.set_password(password)
        
        # Save to database
        user.save(using=self._db)
        
        return user
    
    def create_superuser(self, email, name, password=None, **extra_fields):
        """
        Create and save a superuser with the given email, name and password.
        
        Args:
            email (str): Superuser's email address
            name (str): Superuser's full name
            password (str): Superuser's password
            **extra_fields: Additional fields for user model
            
        Returns:
            User: Created superuser instance
            
        Raises:
            ValueError: If is_staff or is_superuser is not True
        """
        # Set superuser flags
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_email_verified', True)  # Auto-verify superuser email
        
        # Validate flags
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        
        # Create superuser using create_user method
        return self.create_user(email, name, password, **extra_fields)
    
    def create_firebase_user(self, email, name, firebase_uid, auth_provider='google', **extra_fields):
        """
        Create or retrieve user from Firebase authentication (Google, Apple, etc.)
        Prevents duplicate accounts by checking firebase_uid first, then linking
        existing accounts with the same email.
        
        Args:
            email (str): User's email from Firebase or client payload
            name (str): User's name from Firebase or client payload
            firebase_uid (str): Firebase UID
            auth_provider (str): Authentication provider ('google', 'apple')
            **extra_fields: Additional fields
            
        Returns:
            User: Created or existing linked user instance
        """
        # 1. First, check if user already exists with this Firebase UID
        if firebase_uid:
            user = self.filter(firebase_uid=firebase_uid).first()
            if user:
                # Update name if previously placeholder and better name is provided
                if name and (not user.name or user.name.startswith('user_')):
                    user.name = name
                    user.save(update_fields=['name'])
                return user
        
        # 2. If not found by firebase_uid, check if account exists with this email
        if email:
            normalized_email = self.normalize_email(email)
            user = self.filter(email__iexact=normalized_email).first()
            if user:
                # Link existing email-registered user with Firebase UID to prevent duplicate accounts
                update_fields = []
                if not user.firebase_uid and firebase_uid:
                    user.firebase_uid = firebase_uid
                    update_fields.append('firebase_uid')
                if not user.is_email_verified:
                    user.is_email_verified = True
                    update_fields.append('is_email_verified')
                if name and not user.name:
                    user.name = name
                    update_fields.append('name')
                if update_fields:
                    user.save(update_fields=update_fields)
                return user
        
        # 3. If neither exists, create a new user
        if not email:
            raise ValueError(_("An email address is required to create an account."))
        
        if not name:
            name = email.split('@')[0] if email else f"user_{firebase_uid[:8] if firebase_uid else 'closly'}"
        
        extra_fields.setdefault('firebase_uid', firebase_uid)
        extra_fields.setdefault('auth_provider', auth_provider)
        extra_fields.setdefault('is_email_verified', True)
        extra_fields.setdefault('is_active', True)
        
        new_user = self.create_user(email, name, password=None, **extra_fields)
        
        # Send welcome email for newly created social user
        try:
            from .utils import send_welcome_email
            send_welcome_email(new_user)
        except Exception:
            pass
            
        return new_user