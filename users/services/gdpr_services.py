import logging
import os
import json
import zipfile
import io
import urllib.parse
import requests
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def delete_storage_file_safe(file_field_or_path):
    """
    Physically removes a file from local or cloud storage (S3/R2/Storage Box).
    Prevents orphaned public media files under GDPR Article 17.
    """
    if not file_field_or_path:
        return False
    try:
        path = getattr(file_field_or_path, 'name', None) or str(file_field_or_path)
        if path and default_storage.exists(path):
            default_storage.delete(path)
            logger.info(f"GDPR Storage Cleanup: Physically purged {path}")
            return True
    except Exception as e:
        logger.error(f"GDPR Storage Cleanup Error for {file_field_or_path}: {e}")
    return False


def revoke_apple_token_safe(user):
    """
    Executes Apple OAuth token revocation under App Store Guideline 5.1.1(v) & GDPR Art. 17.
    Endpoint: POST https://appleid.apple.com/auth/revoke
    """
    if getattr(user, 'auth_provider', '') != 'apple' and not getattr(user, 'firebase_uid', ''):
        return False

    client_id = getattr(settings, 'APPLE_CLIENT_ID', '') or getattr(settings, 'APPLE_SERVICES_ID', 'com.myclosly.app')
    client_secret = getattr(settings, 'APPLE_CLIENT_SECRET', '')
    token_to_revoke = (
        getattr(user, 'apple_refresh_token', '')
        or getattr(user, 'firebase_uid', '')
        or getattr(user, 'apple_user_id', '')
        or (f"apple_sub_{user.id}" if getattr(user, 'auth_provider', '') == 'apple' else '')
    )

    if not client_id or not token_to_revoke:
        logger.info(f"Apple Revocation: Skipping (no client_id or token available for user {user.id})")
        return False

    revoke_url = "https://appleid.apple.com/auth/revoke"
    payload = {
        'client_id': client_id,
        'token': token_to_revoke,
        'token_type_hint': 'refresh_token',
    }
    if client_secret:
        payload['client_secret'] = client_secret

    try:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        resp = requests.post(revoke_url, data=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"Apple Revocation: Token successfully revoked for user {user.id}")
            return True
        else:
            logger.warning(f"Apple Revocation returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Apple Revocation HTTP error for user {user.id}: {e}")

    return False


def delete_firebase_user_safe(firebase_uid: str):
    """
    Deletes user identity from Firebase Auth server-side via Firebase Admin SDK.
    """
    if not firebase_uid:
        return False
    try:
        import firebase_admin.auth
        firebase_admin.auth.delete_user(firebase_uid)
        logger.info(f"Firebase Auth user {firebase_uid} successfully deleted.")
        return True
    except Exception as e:
        logger.warning(f"Firebase Auth user deletion error for {firebase_uid}: {e}")
        return False


def purge_and_anonymize_user(user):
    """
    Executes complete GDPR Article 17 account erasure and physical media purge.
    1. Physically deletes all uploaded images from cloud storage (S3/disk) across:
       - user.profile_picture
       - ClosetItem.image & FitCheck.raw_image
       - TodayOutfit.image & OutfitImage.image
       - Story.image & Story.video
       - DirectMessage.image
    2. Revokes third-party credentials:
       - Apple OAuth token revocation (POST https://appleid.apple.com/auth/revoke)
       - Firebase Admin user deletion
    3. Purges all private database content and relational entities.
    4. Anonymizes the user record and revokes all outstanding JWT tokens.
    """
    from users.utils.email_utils import send_account_deletion_email
    from users.utils.auth_utils import revoke_all_user_tokens

    # 1. Physical storage erasure across all apps
    # A. User profile picture
    if getattr(user, 'profile_picture', None):
        delete_storage_file_safe(user.profile_picture)

    # B. Closet app images
    try:
        from closet.models import ClosetItem, FitCheck
        for item in ClosetItem.objects.filter(user=user):
            if item.image:
                delete_storage_file_safe(item.image)
            item.delete()
        for fc in FitCheck.objects.filter(user=user):
            if fc.raw_image:
                delete_storage_file_safe(fc.raw_image)
            fc.delete()
    except Exception as e:
        logger.error(f"Error purging closet items for user {user.id}: {e}")

    # C. Social app images (Outfits, Carousel, Stories, DMs)
    try:
        from social.models import TodayOutfit, OutfitImage, Story, DirectMessage
        for outfit in TodayOutfit.objects.filter(user=user):
            if outfit.image:
                delete_storage_file_safe(outfit.image)
            for oi in outfit.images.all():
                if oi.image:
                    delete_storage_file_safe(oi.image)
            outfit.delete()

        for story in Story.objects.filter(user=user):
            if getattr(story, 'image', None):
                delete_storage_file_safe(story.image)
            if getattr(story, 'video', None):
                delete_storage_file_safe(story.video)
            story.delete()

        for dm in DirectMessage.objects.filter(sender=user):
            if dm.image:
                delete_storage_file_safe(dm.image)
            dm.delete()
    except Exception as e:
        logger.error(f"Error purging social media for user {user.id}: {e}")

    # 2. Third-party provider identity revocation
    revoke_apple_token_safe(user)
    if getattr(user, 'firebase_uid', None):
        delete_firebase_user_safe(user.firebase_uid)

    # Revoke all outstanding refresh tokens
    revoke_all_user_tokens(user)

    # Invalidate Redis cache keys
    try:
        from django.core.cache import cache
        cache.delete(f"user_online_{user.id}")
        cache.delete(f"user_last_seen_{user.id}")
        # Clear any cached feed keys
        from affiliate.services.discovery_services import invalidate_user_feed_cache
        invalidate_user_feed_cache(user.id)
    except Exception:
        pass

    # 3. Database relational cleanup
    summary = {
        'name': user.name,
        'email': user.email,
        'date_joined': user.date_joined.strftime('%d %B %Y') if getattr(user, 'date_joined', None) else 'N/A',
        'closet_items_count': 0,
        'outfits_count': 0,
        'lifetime_points': getattr(getattr(user, 'reward_profile', None), 'lifetime_points', 0),
    }

    send_account_deletion_email(user, summary=summary)

    with transaction.atomic():
        from social.models import OutfitLike, StoryView, StoryLike, UserFollow
        OutfitLike.objects.filter(user=user).delete()
        StoryView.objects.filter(viewer=user).delete()
        StoryLike.objects.filter(user=user).delete()
        UserFollow.objects.filter(follower=user).delete()
        UserFollow.objects.filter(following=user).delete()

        from notifications.models import Notification
        Notification.objects.filter(recipient=user).delete()
        Notification.objects.filter(sender=user).delete()

        # Financial Ledger Retention (SR-28):
        from rewards.models import UserRewardProfile, RewardPointTransaction, PointAward, LedgerTxn, AwardStateLog
        profile = UserRewardProfile.objects.filter(user=user).first()
        if profile:
            profile.available_points = 0
            profile.save(update_fields=['available_points'])

        RewardPointTransaction.objects.filter(user=user).update(
            description='Historical reward transaction (user pseudonymized for GDPR)'
        )
        RewardPointTransaction.objects.filter(reference_id=str(user.id)).update(
            reference_id='pseudonymized'
        )
        PointAward.objects.filter(referred_user=user).update(referred_user=None)
        LedgerTxn.objects.filter(award__user=user).update(
            description='Historical ledger transaction (user pseudonymized for GDPR)'
        )
        AwardStateLog.objects.filter(award__user=user).update(
            reason='State transition (user pseudonymized for GDPR)'
        )

        from affiliate.models import Conversion, ProductClick, ProductFavorite
        Conversion.objects.filter(user=user).update(user=None)
        ProductClick.objects.filter(user=user).update(user=None)
        ProductFavorite.objects.filter(user=user).delete()

        from users.models import UserPreference, UserLoginHistory, Device
        UserPreference.objects.filter(user=user).delete()
        UserLoginHistory.objects.filter(user=user).delete()
        Device.objects.filter(user=user).delete()

        # Anonymize user record
        hex_id = str(user.id).replace('-', '')[:10]
        user.name = 'Deleted User'
        user.email = f"deleted_{hex_id}@deleted.myclosly.com"
        user.is_active = False
        user.is_email_verified = False
        user.firebase_uid = None
        user.referral_code = f"DEL-{hex_id.upper()}"
        user.bio = None
        user.country = ''
        user.city = ''
        user.occupation = ''
        user.gender = ''
        user.date_of_birth = None
        user.profile_picture = None
        user.set_unusable_password()
        user.save()

    logger.info(f"GDPR Purge & Anonymization complete for user {user.id}")
    return True


def compile_user_data_export(user) -> dict:
    """
    Compiles full GDPR Article 20 personal data portfolio for export.
    Returns structured dictionary containing all personal records.
    """
    data = {
        'export_metadata': {
            'exported_at': timezone.now().isoformat(),
            'platform': 'My Closly (DACH)',
            'regulation': 'EU GDPR Article 20 (Right to Data Portability)',
            'user_id': str(user.id),
        },
        'profile': {
            'name': user.name,
            'email': user.email,
            'date_joined': user.date_joined.isoformat() if getattr(user, 'date_joined', None) else None,
            'bio': user.bio,
            'country': user.country,
            'city': user.city,
            'occupation': user.occupation,
            'gender': user.gender,
            'date_of_birth': user.date_of_birth.isoformat() if getattr(user, 'date_of_birth', None) else None,
            'preferred_language': user.preferred_language,
            'referral_code': user.referral_code,
        },
        'preferences': {},
        'wardrobe': [],
        'outfits': [],
        'rewards_summary': {},
        'login_history': [],
    }

    # Preferences
    if hasattr(user, 'preferences') and user.preferences:
        p = user.preferences
        data['preferences'] = {
            'style_match': p.style_match,
            'what_do_you_dress_for': p.what_do_you_dress_for,
            'body_type': p.body_type,
            'body_size': p.body_size,
            'shoe_size': p.shoe_size,
            'color_palette': p.color_palette,
            'clothing_categories': p.clothing_categories,
            'preferred_brands': p.preferred_brands,
            'price_band': getattr(p, 'price_band', ''),
            'gender_prefs': getattr(p, 'gender_prefs', []),
            'clothing_sizes': getattr(p, 'clothing_sizes', []),
            'blocked_brands': getattr(p, 'blocked_brands', []),
        }

    # Closet items
    if hasattr(user, 'closet_items'):
        for item in user.closet_items.all():
            data['wardrobe'].append({
                'id': item.id,
                'name': item.name,
                'category': item.category,
                'color': item.color,
                'brand': item.brand,
                'size': item.size,
                'price': str(item.price) if item.price else None,
                'times_worn': item.times_worn,
                'last_worn_at': item.last_worn_at.isoformat() if item.last_worn_at else None,
                'created_at': item.created_at.isoformat() if item.created_at else None,
            })

    # Outfits
    if hasattr(user, 'today_outfits'):
        for outfit in user.today_outfits.all():
            data['outfits'].append({
                'id': outfit.id,
                'caption': outfit.caption,
                'style_category': outfit.style_category,
                'weather_tag': outfit.weather_tag,
                'visibility': outfit.visibility,
                'created_at': outfit.created_at.isoformat() if outfit.created_at else None,
            })

    # Rewards
    if hasattr(user, 'reward_profile') and user.reward_profile:
        rp = user.reward_profile
        data['rewards_summary'] = {
            'available_points': rp.available_points,
            'lifetime_points': rp.lifetime_points,
            'current_tier': rp.current_tier,
        }

    # Login History (Recent 10)
    if hasattr(user, 'login_history'):
        for lh in user.login_history.all()[:10]:
            data['login_history'].append({
                'login_time': lh.login_time.isoformat() if lh.login_time else None,
                'ip_address': lh.ip_address,
                'auth_method': lh.auth_method,
            })
    # Consents
    from users.models import Consent
    data['consents'] = [
        {
            'kind': c.kind,
            'granted': c.granted,
            'occurred_at': c.occurred_at.isoformat() if hasattr(c, 'occurred_at') and c.occurred_at else None,
        }
        for c in Consent.objects.filter(user=user)
    ]

    # Canonical user key alias for backward-compatibility
    data['user'] = data['profile']

    return data


def generate_and_dispatch_user_export_archive(user):
    """
    Generates a secure ZIP archive of personal data, stores it,
    and sends a download notification email to the user.
    """
    export_payload = compile_user_data_export(user)
    json_bytes = json.dumps(export_payload, indent=2, ensure_ascii=False).encode('utf-8')

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('myclosly_data_export.json', json_bytes)

    zip_buffer.seek(0)
    filename = f"exports/{user.id}/myclosly_export_{timezone.now().strftime('%Y%m%d_%H%M%S')}.zip"
    saved_path = default_storage.save(filename, zip_buffer)

    download_url = default_storage.url(saved_path) if hasattr(default_storage, 'url') else f"/media/{saved_path}"
    
    subject = "Your My Closly Data Export is Ready (GDPR Article 20)"
    message = (
        f"Hello {user.name or 'there'},\n\n"
        f"Your requested personal data archive has been compiled in compliance with GDPR Article 20.\n"
        f"You can download your archive directly here:\n{download_url}\n\n"
        f"This file will be automatically purged after 7 days.\n\n"
        f"Best regards,\nMy Closly Privacy Team"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'privacy@myclosly.com'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info(f"GDPR Export email dispatched to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send GDPR Export email to {user.email}: {e}")

    return saved_path
