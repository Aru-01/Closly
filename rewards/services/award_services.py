import uuid
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from rewards.models import (
    PointAward,
    RewardPointTransaction,
    UserRewardProfile,
    LedgerTxn,
    AwardStateLog,
)
from .tier_services import (
    ACTION_POINTS,
    get_point_validity_days,
    get_tier_for_lifetime_points,
)
from .ledger_services import (
    get_or_create_ledger_account,
    create_balanced_ledger_txn,
)

logger = logging.getLogger(__name__)


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


def reconcile_existing_reward_data():
    """
    Reconciles pre-existing RewardPointTransaction rows with the double-entry ledger (Section 5).
    Ensures every historical point has a balanced LedgerTxn, LedgerEntry, and PointAward.
    """
    reconciled_count = 0
    with transaction.atomic():
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
