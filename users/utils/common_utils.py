import secrets
from datetime import date
from django.db import transaction
from .email_utils import send_account_deletion_email


def generate_otp(length=4):
    """
    Generate a random OTP of a given length.
    """
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])


def get_client_ip(request):
    """
    Get client IP address from request.
    
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
    Get user agent string from request.
    
    Args:
        request: Django request object
        
    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def calculate_age(date_of_birth):
    """
    Calculate age from date of birth.
    
    Args:
        date_of_birth (date): Date of birth
        
    Returns:
        int: Age in years
    """
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
    Validate if user meets minimum age requirement.
    
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
