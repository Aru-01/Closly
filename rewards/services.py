import uuid
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from django.db import transaction, models
from django.conf import settings

from .models import (
    UserRewardProfile,
    RewardPointTransaction,
    LedgerAccount,
    PointAward,
    LedgerTxn,
    LedgerEntry,
    AwardStateLog,
)

logger = logging.getLogger(__name__)

# Tier thresholds:
# Bronze: 0 - 2,000
# Silver: 2,000 - 5,000
# Gold: 5,000 - 10,000
# Platinum: 10,000 - 50,000
# Diamond: 50,000+
def get_tier_thresholds():
    return [
        ('Diamond', getattr(settings, 'MYC_TIER_DIAMOND_THRESHOLD', 50000)),
        ('Platinum', getattr(settings, 'MYC_TIER_PLATINUM_THRESHOLD', 10000)),
        ('Gold', getattr(settings, 'MYC_TIER_GOLD_THRESHOLD', 5000)),
        ('Silver', getattr(settings, 'MYC_TIER_SILVER_THRESHOLD', 2000)),
        ('Bronze', 0),
    ]

TIER_THRESHOLDS = get_tier_thresholds()

def get_action_points():
    return {
        'share_look': getattr(settings, 'MYC_POINTS_SHARE_LOOK', 120),
        'invite_friend': getattr(settings, 'MYC_REFERRAL_POINTS', 200),
        'make_purchase': getattr(settings, 'MYC_PURCHASE_AWARD_POINTS', 200),
        'add_closet_item': getattr(settings, 'MYC_POINTS_ADD_CLOSET_ITEM', 50),
    }

ACTION_POINTS = get_action_points()


def get_point_validity_days():
    """Returns point validity duration in days (spec: 24 months, 730 days)."""
    months = getattr(settings, 'MYC_POINTS_EXPIRY_MONTHS', 24)
    return int(round(months * 365 / 12))  # Exactly 730 days for 24 months (2 full years)


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


# ==============================================================================
# Double-Entry Ledger Core Engine (SR-08)
# ==============================================================================

def get_or_create_ledger_account(kind, user=None):
    """
    Retrieves or creates a system-level or user-level ledger account.
    """
    if kind == 'user_available':
        if not user:
            raise ValueError("User must be specified for user_available ledger account")
        account, _ = LedgerAccount.objects.get_or_create(kind=kind, user=user)
        return account
    else:
        account, _ = LedgerAccount.objects.get_or_create(kind=kind, user=None)
        return account


def create_balanced_ledger_txn(txn_type, award=None, conversion_reference='', idempotency_key=None, description='', entries_data=None, created_by=None):
    """
    Creates an atomic double-entry ledger transaction.
    Guarantees: sum(entries.points) == 0.
    Returns existing transaction if idempotency_key is repeated.
    """
    if not idempotency_key:
        idempotency_key = f"{txn_type}:{uuid.uuid4().hex}"

    existing_txn = LedgerTxn.objects.filter(idempotency_key=idempotency_key).first()
    if existing_txn:
        return existing_txn

    if not entries_data or len(entries_data) < 2:
        raise ValueError("Double-entry transaction requires at least two balanced entries")

    total_sum = sum(points for _, points in entries_data)
    if total_sum != 0:
        raise ValueError(f"Ledger transaction unbalanced! Sum of entries is {total_sum}, must be 0.")

    txn = LedgerTxn.objects.create(
        txn_type=txn_type,
        award=award,
        conversion_reference=conversion_reference,
        idempotency_key=idempotency_key,
        description=description,
        created_by=created_by
    )

    for account, points in entries_data:
        LedgerEntry.objects.create(
            txn=txn,
            account=account,
            points=points
        )

    return txn


def transition_award(award, to_state, *, reason='', actor='system', idempotency_key=None, points_delta=None):
    """
    Transitions an award's state machine (RESERVED -> PENDING -> CONFIRMED -> AVAILABLE -> REDEEMED / EXPIRED / CLAWED_BACK)
    and posts the corresponding balanced double-entry ledger entries (SR-08).
    """
    from_state = award.state
    if from_state == to_state and award.ledger_transactions.exists():
        return award

    now = timezone.now()
    points = points_delta if points_delta is not None else award.points_current

    # Determine counter account
    if award.award_type in ('purchase_awin', 'purchase_boutique'):
        counter_kind = 'points_liability_control'
    else:
        counter_kind = 'marketing_expense'

    user_acc = get_or_create_ledger_account('user_available', user=award.user)
    counter_acc = get_or_create_ledger_account(counter_kind)
    breakage_acc = get_or_create_ledger_account('breakage_income')

    if to_state == 'AVAILABLE':
        # Post credit to user available, debit counter account
        # Counter balance: -points, User balance: +points. Sum = 0.
        award.available_at = now
        validity_days = get_point_validity_days()
        award.expires_at = now + timedelta(days=validity_days)
        award.state = 'AVAILABLE'
        award.save(update_fields=['state', 'available_at', 'expires_at', 'updated_at'])

        txn_key = idempotency_key or f"award_avail:{award.id}:{uuid.uuid4().hex[:8]}"
        create_balanced_ledger_txn(
            txn_type=f"{award.award_type}_available",
            award=award,
            conversion_reference=award.conversion_reference,
            idempotency_key=txn_key,
            description=reason or f"Award #{award.id} available (+{points} pts)",
            entries_data=[(counter_acc, -points), (user_acc, points)]
        )

    elif to_state in ('CLAWED_BACK', 'VOID'):
        # Reversal: User balance: -points, Counter balance: +points. Sum = 0.
        award.state = to_state
        award.points_current = 0
        award.save(update_fields=['state', 'points_current', 'updated_at'])

        txn_key = idempotency_key or f"award_reversal:{award.id}:{uuid.uuid4().hex[:8]}"
        create_balanced_ledger_txn(
            txn_type=f"{award.award_type}_reversal",
            award=award,
            conversion_reference=award.conversion_reference,
            idempotency_key=txn_key,
            description=reason or f"Award #{award.id} reversed/clawed back (-{points} pts)",
            entries_data=[(user_acc, -points), (counter_acc, points)]
        )

    elif to_state == 'EXPIRED':
        # Expiry: User balance: -points, Breakage income: +points. Sum = 0.
        award.state = 'EXPIRED'
        award.points_current = 0
        award.save(update_fields=['state', 'points_current', 'updated_at'])

        txn_key = idempotency_key or f"award_expired:{award.id}:{uuid.uuid4().hex[:8]}"
        create_balanced_ledger_txn(
            txn_type="points_expired",
            award=award,
            idempotency_key=txn_key,
            description=reason or f"Award #{award.id} expired after 24 months (-{points} pts)",
            entries_data=[(user_acc, -points), (breakage_acc, points)]
        )

    else:
        award.state = to_state
        award.save(update_fields=['state', 'updated_at'])

    AwardStateLog.objects.create(
        award=award,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        points_delta=points if to_state == 'AVAILABLE' else (-points if to_state in ('CLAWED_BACK', 'VOID', 'EXPIRED') else 0),
        actor=actor
    )

    return award


# ==============================================================================
# Activity Rewards & Fraud Protection (SR-07)
# ==============================================================================

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
            old_tier = profile.current_tier
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


# ==============================================================================
# Referral Rewards (SR-04)
# ==============================================================================

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

            # Check if this referee was already rewarded (DB constraint will also enforce)
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

            # Update or create statement transaction
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


# ==============================================================================
# Expiration Processing (SR-08, SR-24: 24 Months)
# ==============================================================================

def process_expired_points(user, profile=None):
    """
    Evaluates awards/transactions that passed their 24-month validity (SR-08).
    Deducts expired points from available_points using balanced double-entry ledger entries.
    DOES NOT deduct from lifetime_points (user's tier is preserved permanently).
    """
    now = timezone.now()

    with transaction.atomic():
        profile, _ = UserRewardProfile.objects.select_for_update().get_or_create(user=user)

        expired_txs = list(RewardPointTransaction.objects.select_for_update().filter(
            user=user,
            is_expired=False,
            expires_at__isnull=False,
            expires_at__lte=now,
            points__gt=0
        ))

        expired_awards = list(PointAward.objects.select_for_update().filter(
            user=user,
            state='AVAILABLE',
            expires_at__isnull=False,
            expires_at__lte=now,
            points_current__gt=0
        ))

        if not expired_txs and not expired_awards:
            return 0

        total_expired = 0
        for tx in expired_txs:
            tx.is_expired = True
            tx.save(update_fields=['is_expired'])
            total_expired += tx.points

        for award in expired_awards:
            pts = award.points_current
            transition_award(
                award=award,
                to_state='EXPIRED',
                reason=f"24-month expiration on {award.id}"
            )

        if total_expired > 0:
            profile.available_points = max(0, profile.available_points - total_expired)
            profile.save(update_fields=['available_points'])

            validity_months = getattr(settings, 'MYC_POINTS_EXPIRY_MONTHS', 24)
            RewardPointTransaction.objects.create(
                user=user,
                action_type='points_expired',
                points=-total_expired,
                description=f"{total_expired} points expired after {validity_months} months validity."
            )

            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=user,
                    notification_type='points_expired',
                    title='Points Expired Notice',
                    message=f"{total_expired} points have expired after {validity_months} months. Your tier status remains preserved!",
                    data={'expired_points': total_expired, 'available_points': profile.available_points}
                )
            except Exception as e:
                logger.debug(f"Failed to dispatch expiration notification: {e}")

        return total_expired


# ==============================================================================
# General / Compatibility Points Awarding
# ==============================================================================

def award_points(user, action_type, description=None, reference_id='', points_override=None):
    """
    Awards points to user with double-entry ledger integration and 24-month validity.
    """
    points = points_override if points_override is not None else ACTION_POINTS.get(action_type, 0)
    if points <= 0:
        return None

    if not description:
        description = dict(RewardPointTransaction.ACTION_CHOICES).get(
            action_type,
            action_type.replace('_', ' ').title()
        )

    validity_days = get_point_validity_days()
    expires_at = timezone.now() + timedelta(days=validity_days)

    try:
        with transaction.atomic():
            profile, _ = UserRewardProfile.objects.select_for_update().get_or_create(user=user)
            old_tier = profile.current_tier

            # 1. Create statement row
            tx = RewardPointTransaction.objects.create(
                user=user,
                action_type=action_type,
                points=points,
                description=description,
                reference_id=str(reference_id),
                expires_at=expires_at
            )

            # 2. Create PointAward and balanced LedgerTxn
            award_type = action_type if action_type in dict(PointAward.AWARD_TYPES) else 'manual_goodwill'
            award = PointAward.objects.create(
                user=user,
                award_type=award_type,
                points_original=points,
                points_current=points,
                state='PENDING',
                conversion_reference=str(reference_id) if action_type == 'make_purchase' else '',
                available_at=timezone.now(),
                expires_at=expires_at
            )

            transition_award(
                award=award,
                to_state='AVAILABLE',
                reason=description,
                idempotency_key=f"award:{action_type}:{user.id}:{reference_id or uuid.uuid4().hex[:8]}"
            )

            # 3. Update cached balance
            profile.available_points += points
            profile.lifetime_points += points
            new_tier = get_tier_for_lifetime_points(profile.lifetime_points)
            profile.current_tier = new_tier
            profile.save(update_fields=['available_points', 'lifetime_points', 'current_tier', 'tier_updated_at'])

            # 4. In-App Notifications
            try:
                from notifications.services import create_notification
                validity_months = getattr(settings, 'MYC_POINTS_EXPIRY_MONTHS', 24)
                create_notification(
                    recipient=user,
                    notification_type='points_earned',
                    title=f'+{points} Closet Points Earned!',
                    message=f"You earned {points} points for: {description}. Valid for {validity_months} months.",
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
                logger.debug(f"Failed to dispatch notification: {e}")

            return tx
    except Exception as e:
        logger.error(f"Failed to award points to {user.email}: {e}")
        return None


def reconcile_existing_reward_data():
    """
    Reconciles pre-existing RewardPointTransaction rows with the double-entry ledger (Section 5).
    Ensures every historical point has a balanced LedgerTxn, LedgerEntry, and PointAward.
    """
    reconciled_count = 0
    with transaction.atomic():
        # Ensure system accounts exist
        get_or_create_ledger_account('points_liability_control')
        get_or_create_ledger_account('marketing_expense')
        get_or_create_ledger_account('commission_revenue')
        get_or_create_ledger_account('breakage_income')

        for tx in RewardPointTransaction.objects.filter(points__gt=0).order_by('created_at'):
            get_or_create_ledger_account('user_available', user=tx.user)

            txn_key = f"reconcile:tx:{tx.id}"
            existing_txn = LedgerTxn.objects.filter(idempotency_key=txn_key).first()
            if existing_txn:
                continue

            award_type = tx.action_type if tx.action_type in dict(PointAward.AWARD_TYPES) else 'manual_goodwill'
            # Find existing unlinked award or create new one
            award = PointAward.objects.filter(
                user=tx.user,
                award_type=award_type,
                points_original=tx.points,
                conversion_reference=tx.reference_id if tx.action_type == 'make_purchase' else '',
                ledger_transactions__isnull=True
            ).first()

            if not award:
                award = PointAward.objects.create(
                    user=tx.user,
                    award_type=award_type,
                    points_original=tx.points,
                    points_current=tx.points,
                    state='PENDING',
                    conversion_reference=tx.reference_id if tx.action_type == 'make_purchase' else '',
                    available_at=tx.created_at,
                    expires_at=tx.expires_at or (tx.created_at + timedelta(days=get_point_validity_days()))
                )

            transition_award(
                award=award,
                to_state='AVAILABLE',
                reason=f"Reconciled transaction #{tx.id}: {tx.description}",
                idempotency_key=txn_key
            )
            reconciled_count += 1

    logger.info(f"Reconciled {reconciled_count} reward transactions into double-entry ledger.")
    return reconciled_count
