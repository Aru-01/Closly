from datetime import timedelta
from django.utils import timezone
from django.db import transaction
import logging

from .models import UserRewardProfile, RewardPointTransaction

logger = logging.getLogger(__name__)

# Tier thresholds as requested:
# Bronze: 0 - 2,000
# Silver: 2,000 - 5,000
# Gold: 5,000 - 10,000
# Platinum: 10,000 - 50,000
# Diamond: 50,000+
TIER_THRESHOLDS = [
    ('Diamond', 50000),
    ('Platinum', 10000),
    ('Gold', 5000),
    ('Silver', 2000),
    ('Bronze', 0),
]

ACTION_POINTS = {
    'share_look': 120,       # Share a look
    'invite_friend': 200,    # Invite friends
    'make_purchase': 200,    # Make a purchase
    'add_closet_item': 50,   # Add to closet
}

POINT_VALIDITY_DAYS = 60


def get_tier_for_lifetime_points(lifetime_points):
    """Determine tier name based on lifetime achievement points."""
    for tier, threshold in TIER_THRESHOLDS:
        if lifetime_points >= threshold:
            return tier
    return 'Bronze'


def get_tier_info(lifetime_points, available_points=None):
    """
    Returns current tier, next tier, points needed to reach next tier,
    and progress percentage based on permanent lifetime achievement points.
    """
    current_tier = get_tier_for_lifetime_points(lifetime_points)

    if current_tier == 'Bronze':
        next_tier = 'Silver'
        min_pts = 0
        target_pts = 2000
        points_to_next = max(0, target_pts - lifetime_points)
        progress_percentage = min(100.0, round((lifetime_points / target_pts) * 100, 1))
    elif current_tier == 'Silver':
        next_tier = 'Gold'
        min_pts = 2000
        target_pts = 5000
        points_to_next = max(0, target_pts - lifetime_points)
        progress_percentage = min(100.0, round(((lifetime_points - min_pts) / (target_pts - min_pts)) * 100, 1))
    elif current_tier == 'Gold':
        next_tier = 'Platinum'
        min_pts = 5000
        target_pts = 10000
        points_to_next = max(0, target_pts - lifetime_points)
        progress_percentage = min(100.0, round(((lifetime_points - min_pts) / (target_pts - min_pts)) * 100, 1))
    elif current_tier == 'Platinum':
        next_tier = 'Diamond'
        min_pts = 10000
        target_pts = 50000
        points_to_next = max(0, target_pts - lifetime_points)
        progress_percentage = min(100.0, round(((lifetime_points - min_pts) / (target_pts - min_pts)) * 100, 1))
    else:  # Diamond
        next_tier = None
        points_to_next = 0
        progress_percentage = 100.0

    return {
        'current_tier': current_tier,
        'next_tier': next_tier,
        'points_to_next_tier': points_to_next,
        'tier_progress_percentage': progress_percentage,
        'exp_summary': f"{points_to_next:,} points needed for {next_tier}" if next_tier else "Top Tier reached! You are Diamond.",
    }


def process_expired_points(user, profile=None):
    """
    Evaluates transactions that passed their 60-day validity.
    Deducts expired points from available_points.
    DOES NOT deduct from lifetime_points (user's tier is preserved permanently).
    """
    now = timezone.now()
    if profile is None:
        profile, _ = UserRewardProfile.objects.get_or_create(user=user)

    expired_txs = RewardPointTransaction.objects.filter(
        user=user,
        is_expired=False,
        expires_at__isnull=False,
        expires_at__lte=now,
        points__gt=0
    )

    if not expired_txs.exists():
        return 0

    total_expired = 0
    with transaction.atomic():
        for tx in expired_txs:
            tx.is_expired = True
            tx.save(update_fields=['is_expired'])
            total_expired += tx.points

        if total_expired > 0:
            profile.available_points = max(0, profile.available_points - total_expired)
            profile.save(update_fields=['available_points'])

            # Log an expiration event in ledger
            RewardPointTransaction.objects.create(
                user=user,
                action_type='points_expired',
                points=-total_expired,
                description=f"{total_expired} points expired after {POINT_VALIDITY_DAYS} days validity."
            )

            # Send in-app notification
            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=user,
                    notification_type='points_expired',
                    title='Points Expired Notice',
                    message=f"{total_expired} points have expired after 60 days. Your tier status remains preserved!",
                    data={'expired_points': total_expired, 'available_points': profile.available_points}
                )
            except Exception as e:
                logger.debug(f"Failed to dispatch expiration notification: {e}")

    return total_expired


def award_points(user, action_type, description=None, reference_id='', points_override=None):
    """
    Awards points to user:
    - Increments available_points (valid for 60 days)
    - Increments lifetime_points (never decreases, sets tier)
    - Automatically updates tier if milestone achieved
    - Sends in-app notifications
    """
    points = points_override if points_override is not None else ACTION_POINTS.get(action_type, 0)
    if points <= 0:
        return None

    if not description:
        description = dict(RewardPointTransaction.ACTION_CHOICES).get(
            action_type,
            action_type.replace('_', ' ').title()
        )

    expires_at = timezone.now() + timedelta(days=POINT_VALIDITY_DAYS)

    try:
        with transaction.atomic():
            # 1. Create transaction with 60-day expiry
            tx = RewardPointTransaction.objects.create(
                user=user,
                action_type=action_type,
                points=points,
                description=description,
                reference_id=str(reference_id),
                expires_at=expires_at
            )

            # 2. Update user reward profile
            profile, _ = UserRewardProfile.objects.get_or_create(user=user)
            old_tier = profile.current_tier

            profile.available_points += points
            profile.lifetime_points += points

            new_tier = get_tier_for_lifetime_points(profile.lifetime_points)
            profile.current_tier = new_tier
            profile.save()

            # 3. In-App Notifications
            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=user,
                    notification_type='points_earned',
                    title=f'+{points} Closet Points Earned!',
                    message=f"You earned {points} points for: {description}. Valid for 60 days.",
                    data={
                        'points': points,
                        'available_points': profile.available_points,
                        'lifetime_points': profile.lifetime_points,
                        'current_tier': new_tier
                    }
                )

                if new_tier != old_tier:
                    create_notification(
                        recipient=user,
                        notification_type='tier_upgrade',
                        title=f'🎉 Level Up! You reached {new_tier} Tier!',
                        message=f"Congratulations! You permanently unlocked {new_tier} tier with {profile.lifetime_points:,} lifetime points.",
                        data={'old_tier': old_tier, 'new_tier': new_tier, 'lifetime_points': profile.lifetime_points}
                    )
            except Exception as e:
                logger.debug(f"Failed to dispatch notification during point award: {e}")

            return tx
    except Exception as e:
        logger.error(f"Failed to award points to {user.email}: {e}")
        return None
