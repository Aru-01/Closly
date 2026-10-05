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
    
    @classmethod
    def normalize_email(cls, email):
        """
        Normalize the email address by lowercasing both the local and domain parts.
        """
        email = email or ''
        try:
            email_name, domain_part = email.strip().rsplit('@', 1)
        except ValueError:
            pass
        else:
            email = email_name.lower() + '@' + domain_part.lower()
        return email.strip().lower()

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
        
        # Normalize email (lowercase full address)
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
    
    def create_firebase_user(self, email, name, firebase_uid, auth_provider='google', photo_url=None, email_verified=True, **extra_fields):
        """
        Create or retrieve user from Firebase authentication (Google, Apple, etc.)
        Requires verified email from token. Links existing accounts safely.
        
        Args:
            email (str): Verified email from Firebase ID token
            name (str): User's name from Firebase token or profile
            firebase_uid (str): Firebase UID
            auth_provider (str): Whitelisted authentication provider ('google', 'apple')
            photo_url (str): Verified avatar URL from provider token
            email_verified (bool): Provider email verification claim (must be True)
            **extra_fields: Additional fields
            
        Returns:
            User: Created or existing linked user instance
        """
        if not email or not email_verified:
            raise ValueError(_("Firebase authentication requires a verified email address from the identity provider."))

        normalized_email = self.normalize_email(email)

        # 1. First, check if user already exists with this Firebase UID
        if firebase_uid:
            user = self.filter(firebase_uid=firebase_uid).first()
            if user:
                # Update name if previously placeholder and better name is provided
                if name and (not user.name or user.name.startswith('user_')):
                    user.name = name
                    user.save(update_fields=['name'])
                # Download and set profile picture if user doesn't have one yet
                if photo_url and not user.profile_picture:
                    from .utils import save_profile_picture_from_url
                    save_profile_picture_from_url(user, photo_url)
                return user
        
        # 2. Check if account exists with this verified email
        user = self.filter(email__iexact=normalized_email).first()
        if user:
            update_fields = []
            if not user.firebase_uid and firebase_uid:
                user.firebase_uid = firebase_uid
                update_fields.append('firebase_uid')
            if not user.is_email_verified:
                user.is_email_verified = True
                update_fields.append('is_email_verified')
            # Activate unverified email signup if social provider verified email
            if not user.is_active:
                user.is_active = True
                update_fields.append('is_active')
            if name and not user.name:
                user.name = name
                update_fields.append('name')
            if update_fields:
                user.save(update_fields=update_fields)
            if photo_url and not user.profile_picture:
                from .utils import save_profile_picture_from_url
                save_profile_picture_from_url(user, photo_url)
            return user
        
        # 3. Create new social user
        if not name:
            name = email.split('@')[0] if email else f"user_{firebase_uid[:8] if firebase_uid else 'closly'}"
        
        extra_fields.setdefault('firebase_uid', firebase_uid)
        extra_fields.setdefault('auth_provider', auth_provider)
        extra_fields.setdefault('is_email_verified', True)
        extra_fields.setdefault('is_active', True)
        
        new_user = self.create_user(normalized_email, name, password=None, **extra_fields)

        # Download avatar if safe social URL provided
        if photo_url:
            from .utils import save_profile_picture_from_url
            save_profile_picture_from_url(new_user, photo_url)
        
        # Send welcome email asynchronously
        try:
            from .utils import send_welcome_email
            send_welcome_email(new_user)
        except Exception:
            pass
            
        return new_user