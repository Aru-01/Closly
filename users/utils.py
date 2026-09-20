"""
Utility functions for user authentication and token management
"""

import secrets
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth


# Initialize Firebase Admin SDK
def initialize_firebase():
    """
    Initialize Firebase Admin SDK with service account credentials
    This should be called once when Django starts
    """
    if not firebase_admin._apps:
        firebase_credentials_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
        if not firebase_credentials_path:
            print("Warning: FIREBASE_CREDENTIALS_PATH is not set in settings. Firebase Admin SDK will not be initialized.")
            return

        cred = credentials.Certificate(firebase_credentials_path)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully")


def generate_otp(length=4):
    """
    Generate a random OTP of a given length
    """
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])

def send_otp_email(user, otp):
    """
    Send OTP to user's email
    """
    try:
        subject = 'Your Closly Verification Code'
        html_message = render_to_string('emails/otp_email.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Error sending OTP email: {str(e)}")
        return False


def verify_firebase_token(id_token):
    """
    Verify Firebase ID token and return decoded token data
    
    Args:
        id_token (str): Firebase ID token from client
        
    Returns:
        dict: Decoded token data with user info
        
    Raises:
        Exception: If token is invalid or expired
    """
    try:
        # Verify the ID token and decode it
        decoded_token = firebase_auth.verify_id_token(id_token, clock_skew_seconds=5)
        return decoded_token
    except Exception as e:
        raise Exception(f"Invalid Firebase token: {str(e)}")


def get_client_ip(request):
    """
    Get client IP address from request
    
    Args:
        request: Django request object
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """
    Get user agent string from request
    
    Args:
        request: Django request object
        
    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def send_verification_email(user, verification_url):
    """
    Send email verification link to user
    
    Args:
        user: User instance
        verification_url (str): Full URL for email verification
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Verify Your Email Address'
        
        # Render HTML email template
        html_message = render_to_string('emails/verify_email.html', {
            'user': user,
            'verification_url': verification_url,
            'site_name': 'Closly',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    
    except Exception as e:
        print(f"Error sending verification email: {str(e)}")
        return False


def send_password_reset_email(user, otp):
    """
    Send password reset OTP to user
    
    Args:
        user: User instance
        otp (str): One-time password for reset
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Reset Your Password - Closly'
        
        # Render HTML email template
        html_message = render_to_string('emails/reset_password.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Closly',
            'expiry_minutes': 10,
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    
    except Exception as e:
        print(f"Error sending password reset email: {str(e)}")
        return False


def send_welcome_email(user):
    """
    Send welcome email to newly registered user
    
    Args:
        user: User instance
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Welcome to Closly!'
        
        # Render HTML email template
        html_message = render_to_string('emails/welcome.html', {
            'user': user,
            'site_name': 'Closly',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    
    except Exception as e:
        print(f"Error sending welcome email: {str(e)}")
        return False


def send_account_deletion_email(user, summary=None):
    """
    Send confirmation email when account is deleted
    
    Args:
        user: User instance
        summary (dict, optional): Final account stats summary
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Your Closly Account Has Been Deleted'
        
        # Render HTML email template
        html_message = render_to_string('emails/account_deleted.html', {
            'user': user,
            'summary': summary or {},
            'site_name': 'Closly',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    
    except Exception as e:
        print(f"Error sending account deletion email: {str(e)}")
        return False


def purge_and_anonymize_user(user):
    """
    Executes full GDPR-compliant account purge and user anonymization.
    1. Gathers final profile and wardrobe summary statistics.
    2. Sends account export and confirmation email to user's registered email.
    3. Purges all private content:
       - Closet items
       - Today outfits (posts, images, tags)
       - Story items, likes, views
       - Follows (both followers and followings)
       - Notifications
       - Rewards profile & transactions
       - Preferences and login history
    4. Deletes profile picture from storage.
    5. Anonymizes the user record:
       - name = 'Deleted User'
       - email = f"deleted_{uuid}@deleted.closly.app"
       - is_active = False
       - set_unusable_password()
       - clears PII (bio, location, dob, gender, etc.)
    6. Preserves past direct messages so chat partners don't lose their conversation history,
       while the counterpart author appears as 'Deleted User'.
    """
    from django.db import transaction

    # 1. Gather summary statistics before deletion
    summary = {
        'name': user.name,
        'email': user.email,
        'date_joined': user.date_joined.strftime('%d %B %Y') if user.date_joined else 'N/A',
        'closet_items_count': user.closet_items.count() if hasattr(user, 'closet_items') else 0,
        'outfits_count': user.today_outfits.count() if hasattr(user, 'today_outfits') else 0,
        'lifetime_points': getattr(getattr(user, 'reward_profile', None), 'lifetime_points', 0),
    }

    # 2. Send data export & confirmation email
    send_account_deletion_email(user, summary=summary)

    with transaction.atomic():
        # 3. Purge private user content
        try:
            from closet.models import ClosetItem
            ClosetItem.objects.filter(user=user).delete()
        except Exception:
            pass

        try:
            from social.models import TodayOutfit, OutfitLike, Story, StoryView, StoryLike, UserFollow
            TodayOutfit.objects.filter(user=user).delete()
            OutfitLike.objects.filter(user=user).delete()
            Story.objects.filter(user=user).delete()
            StoryView.objects.filter(viewer=user).delete()
            StoryLike.objects.filter(user=user).delete()
            UserFollow.objects.filter(follower=user).delete()
            UserFollow.objects.filter(following=user).delete()
        except Exception:
            pass

        try:
            from notifications.models import Notification
            Notification.objects.filter(recipient=user).delete()
            Notification.objects.filter(sender=user).delete()
        except Exception:
            pass

        try:
            from rewards.models import UserRewardProfile, RewardPointTransaction
            RewardPointTransaction.objects.filter(user=user).delete()
            UserRewardProfile.objects.filter(user=user).delete()
        except Exception:
            pass

        try:
            from users.models import UserPreferences, UserLoginHistory
            UserPreferences.objects.filter(user=user).delete()
            UserLoginHistory.objects.filter(user=user).delete()
        except Exception:
            pass

        # 4. Remove profile picture from disk
        if user.profile_picture:
            try:
                user.profile_picture.delete(save=False)
            except Exception:
                pass

        # 5. Anonymize user record
        hex_id = str(user.id).replace('-', '')[:10]
        user.name = 'Deleted User'
        user.email = f"deleted_{hex_id}@deleted.closly.app"
        user.is_active = False
        user.is_email_verified = False
        user.is_subscribed = False
        user.set_unusable_password()
        user.profile_picture = None
        user.bio = None
        user.country = None
        user.city = None
        user.occupation = None
        user.gender = None
        user.date_of_birth = None
        user.firebase_uid = None
        user.otp = None
        user.referral_code = None
        user.save()

    return True


def calculate_age(date_of_birth):
    """
    Calculate age from date of birth
    
    Args:
        date_of_birth (date): Date of birth
        
    Returns:
        int: Age in years
    """
    from datetime import date
    
    if not date_of_birth:
        return None
    
    today = date.today()
    age = today.year - date_of_birth.year
    
    # Adjust if birthday hasn't occurred this year
    if today.month < date_of_birth.month or \
       (today.month == date_of_birth.month and today.day < date_of_birth.day):
        age -= 1
    
    return age


def validate_age(date_of_birth, min_age=13):
    """
    Validate if user meets minimum age requirement
    
    Args:
        date_of_birth (date): Date of birth
        min_age (int): Minimum age required (default 13)
        
    Returns:
        bool: True if user meets age requirement, False otherwise
    """
    age = calculate_age(date_of_birth)
    
    if age is None:
        return False
    
    return age >= min_age


def build_absolute_media_url(file_or_url, request=None):
    """
    Constructs a fully qualified absolute URL with scheme and host for media files.
    Ensures URLs start with 'https://' when configured or when accessed via secure proxies.
    """
    if not file_or_url:
        return None

    if hasattr(file_or_url, 'url'):
        try:
            raw_url = file_or_url.url
        except Exception:
            return None
    else:
        raw_url = str(file_or_url)

    if not raw_url:
        return None

    # If it's already a full URL
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        if getattr(settings, 'FORCE_HTTPS_MEDIA_URL', False) and raw_url.startswith('http://'):
            return 'https://' + raw_url[7:]
        return raw_url

    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    if not raw_url.startswith(media_url):
        clean_path = f"{media_url.rstrip('/')}/{raw_url.lstrip('/')}"
    else:
        clean_path = raw_url if raw_url.startswith('/') else f"/{raw_url}"

    # Try building with request first if available
    if request is not None:
        try:
            abs_url = request.build_absolute_uri(clean_path)
            if getattr(settings, 'FORCE_HTTPS_MEDIA_URL', False) and abs_url.startswith('http://'):
                abs_url = 'https://' + abs_url[7:]
            return abs_url
        except Exception:
            pass

    # Fallback to BACKEND_URL setting
    backend_url = getattr(settings, 'BACKEND_URL', '') or ''
    if backend_url:
        base = backend_url.rstrip('/')
        if getattr(settings, 'FORCE_HTTPS_MEDIA_URL', False) and base.startswith('http://'):
            base = 'https://' + base[7:]
        return f"{base}{clean_path}"

    return clean_path