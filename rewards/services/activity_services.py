import logging
from zoneinfo import ZoneInfo
from datetime import timedelta
from django.utils import timezone
from django.db import transaction, models
from django.conf import settings

from rewards.models import (
    PointAward,
    RewardPointTransaction,
    UserRewardProfile,
)
from .tier_services import (
    ACTION_POINTS,
    get_point_validity_days,
    get_tier_for_lifetime_points,
)
from .award_services import transition_award

logger = logging.getLogger(__name__)


def record_activity_reward(user, outfit):
    """
    Awards activity points (+120) for sharing a today outfit look (SR-07).
    Enforces all business constraints:
    1. Gated by MYC_POINTS_ACTIVITY_AWARDS flag.
    2. Public looks ONLY: private outfits receive ZERO points at business service level.
    3. Daily velocity cap: max 120 points/day in Europe/Berlin date, race-safe under row locks.
    4. Idempotent: same outfit will never award points twice.
    """
    if not getattr(settings, 'MYC_POINTS_ACTIVITY_AWARDS', False):
        return None

    if not outfit or getattr(outfit, 'visibility', 'public') != 'public':
        logger.info(f"Activity award rejected: Outfit {getattr(outfit, 'id', None)} is not public.")
        return None

    outfit_id = outfit.id
    if not outfit_id:
        return None

    berlin_now = timezone.now().astimezone(ZoneInfo("Europe/Berlin"))
    berlin_today = berlin_now.date()
    daily_cap = getattr(settings, 'MYC_ACTIVITY_POINTS_DAILY_CAP', 120)

    try:
        with transaction.atomic():
            profile, _ = UserRewardProfile.objects.select_for_update().get_or_create(user=user)

            # Idempotency check: outfit already rewarded?
            existing_award = PointAward.objects.filter(
                user=user,
                award_type='share_look',
                outfit_id=outfit_id
            ).first()
            if existing_award:
                return existing_award

            # Daily cap check in Europe/Berlin date
            today_awarded = PointAward.objects.filter(
                user=user,
                award_type='share_look',
                state='AVAILABLE',
                created_at__date=berlin_today
            ).aggregate(total=models.Sum('points_original'))['total'] or 0

            if today_awarded >= daily_cap:
                logger.info(f"Activity award daily cap ({daily_cap} pts) reached for {user.email}")
                return None

            points = ACTION_POINTS.get('share_look', 120)
            idempotency_key = f"share_look:{user.id}:{outfit_id}"

            award = PointAward.objects.create(
                user=user,
                award_type='share_look',
                points_original=points,
                points_current=points,
                state='PENDING',
                outfit_id=outfit_id,
                available_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=get_point_validity_days())
            )

            transition_award(
                award=award,
                to_state='AVAILABLE',
                reason=f"Shared public outfit look #{outfit_id}",
                idempotency_key=idempotency_key
            )

            # Update cached profile
            profile.available_points += points
            profile.lifetime_points += points
            new_tier = get_tier_for_lifetime_points(profile.lifetime_points)
            profile.current_tier = new_tier
            profile.save(update_fields=['available_points', 'lifetime_points', 'current_tier', 'tier_updated_at'])

            # Create statement row for UI compatibility
            RewardPointTransaction.objects.create(
                user=user,
                action_type='share_look',
                points=points,
                description=f"Shared public look #{outfit_id}",
                reference_id=str(outfit_id),
                expires_at=award.expires_at
            )

            # In-App Notification
            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=user,
                    notification_type='points_earned',
                    title=f'+{points} Points Earned!',
                    message=f"You earned {points} points for sharing your look!",
                    data={'points': points, 'available_points': profile.available_points}
                )
            except Exception as e:
                logger.debug(f"Failed to dispatch notification: {e}")

            return award
    except Exception as e:
        logger.error(f"Failed to record activity reward for user {user.email}: {e}")
        return None


def reverse_activity_reward(user, outfit_id):
    """
    Reverses activity points when the associated public outfit is deleted (SR-07).
    Claws back points, creates balanced ledger entries, and preserves immutable audit trail.
    """
    if not outfit_id:
        return False

    try:
        with transaction.atomic():
            profile, _ = UserRewardProfile.objects.select_for_update().get_or_create(user=user)

            award = PointAward.objects.select_for_update().filter(
                user=user,
                award_type='share_look',
                outfit_id=outfit_id,
                state='AVAILABLE'
            ).first()

            if not award or award.points_current <= 0:
                return False

            reversal_points = award.points_current

            transition_award(
                award=award,
                to_state='CLAWED_BACK',
                reason=f"Reversal for deleted outfit #{outfit_id}",
                idempotency_key=f"reversal:share_look:{outfit_id}"
            )

            profile.available_points = max(0, profile.available_points - reversal_points)
            profile.save(update_fields=['available_points'])

            RewardPointTransaction.objects.create(
                user=user,
                action_type='points_reversal',
                points=-reversal_points,
                description=f"Reversal for deleted outfit #{outfit_id}",
                reference_id=str(outfit_id)
            )

            logger.info(f"Successfully reversed {reversal_points} points for deleted outfit #{outfit_id} from {user.email}")
            return True
    except Exception as e:
        logger.error(f"Failed to reverse activity reward for outfit {outfit_id}: {e}")
        return False


def activate_referral_reward(referred_user):
    """
    Activates referral reward (+200) once referred user completes verification (SR-04).
    Enforces:
    1. One reward per referred user via PointAward DB constraint.
    2. Weekly velocity cap (MYC_REFERRAL_WEEKLY_CAP = 5).
    3. Self-referral forbidden.
    4. Balanced double-entry ledger posting.
    """
    referrer = getattr(referred_user, 'referred_by', None)
    if not referrer:
        return None

    if referrer.id == referred_user.id:
        logger.warning(f"Self-referral rejected for user {referrer.email}")
        return None

    weekly_cap = getattr(settings, 'MYC_REFERRAL_WEEKLY_CAP', 5)
    seven_days_ago = timezone.now() - timedelta(days=7)

    try:
        with transaction.atomic():
            profile, _ = UserRewardProfile.objects.select_for_update().get_or_create(user=referrer)

            existing_award = PointAward.objects.filter(
                award_type='referral_active',
                referred_user=referred_user
            ).first()
            if existing_award:
                return existing_award

            # Weekly velocity cap check
            recent_referrals = PointAward.objects.filter(
                user=referrer,
                award_type='referral_active',
                state='AVAILABLE',
                created_at__gte=seven_days_ago
            ).count()

            if recent_referrals >= weekly_cap:
                logger.info(f"Referral weekly cap ({weekly_cap}) reached for {referrer.email}")
                return None

            points = getattr(settings, 'MYC_REFERRAL_POINTS', 200)
            idempotency_key = f"ref_active:{referrer.id}:{referred_user.id}"

            award = PointAward.objects.create(
                user=referrer,
                award_type='referral_active',
                points_original=points,
                points_current=points,
                state='PENDING',
                referred_user=referred_user,
                available_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=get_point_validity_days())
            )

            transition_award(
                award=award,
                to_state='AVAILABLE',
                reason=f"Referral reward for activated friend {referred_user.name or referred_user.email}",
                idempotency_key=idempotency_key
            )

            profile.available_points += points
            profile.lifetime_points += points
            new_tier = get_tier_for_lifetime_points(profile.lifetime_points)
            profile.current_tier = new_tier
            profile.save(update_fields=['available_points', 'lifetime_points', 'current_tier', 'tier_updated_at'])

            pending_tx = RewardPointTransaction.objects.filter(
                user=referrer,
                action_type='invite_friend',
                reference_id=str(referred_user.id),
                status='pending'
            ).first()

            if pending_tx:
                pending_tx.status = 'completed'
                pending_tx.points = points
                pending_tx.description = f"Referral reward for {referred_user.name or referred_user.email}"
                pending_tx.expires_at = award.expires_at
                pending_tx.save(update_fields=['status', 'points', 'description', 'expires_at'])
            else:
                RewardPointTransaction.objects.create(
                    user=referrer,
                    action_type='invite_friend',
                    points=points,
                    status='completed',
                    description=f"Referral reward for {referred_user.name or referred_user.email}",
                    reference_id=str(referred_user.id),
                    expires_at=award.expires_at
                )

            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=referrer,
                    notification_type='points_earned',
                    title=f'+{points} Referral Points Earned!',
                    message=f"Your friend {referred_user.name or 'a friend'} verified their account! You earned {points} points.",
                    data={'points': points, 'available_points': profile.available_points}
                )
            except Exception as e:
                logger.debug(f"Failed to dispatch referral notification: {e}")

            return award
    except Exception as e:
        logger.error(f"Failed to activate referral reward: {e}")
        return None


def record_pending_referral_reward(referrer, referred_user):
    """
    Creates a pending referral transaction upon user registration (SR-04).
    Points remain 0 until activation via activate_referral_reward.
    """
    if not referrer or not referred_user or referrer == referred_user:
        return None

    existing = RewardPointTransaction.objects.filter(
        user=referrer,
        action_type='invite_friend',
        reference_id=str(referred_user.id)
    ).first()
    if existing:
        return existing

    return RewardPointTransaction.objects.create(
        user=referrer,
        action_type='invite_friend',
        points=0,
        status='pending',
        description=f"Pending referral reward for {referred_user.name or referred_user.email}",
        reference_id=str(referred_user.id)
    )
