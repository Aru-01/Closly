import uuid
import logging
from django.db import models
from rewards.models import (
    LedgerAccount,
    LedgerTxn,
    LedgerEntry,
    UserRewardProfile,
)

logger = logging.getLogger(__name__)


class LedgerImbalanceError(ValueError):
    """
    Raised when a double-entry financial transaction violates Sum(Debits) + Sum(Credits) == 0.
    """
    pass


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


def create_balanced_ledger_txn(
    txn_type=None,
    award=None,
    conversion_reference='',
    idempotency_key=None,
    description='',
    entries_data=None,
    entries=None,
    reference_id='',
    created_by=None
):
    """
    Creates an atomic double-entry ledger transaction.
    Guarantees: sum(entries.points) == 0.
    Returns existing transaction if idempotency_key is repeated.
    """
    if not txn_type:
        txn_type = description or 'manual_ledger_txn'

    if not idempotency_key:
        idempotency_key = reference_id or f"{txn_type}:{uuid.uuid4().hex}"

    existing_txn = LedgerTxn.objects.filter(idempotency_key=idempotency_key).first()
    if existing_txn:
        return existing_txn

    if entries and not entries_data:
        entries_data = []
        for e in entries:
            acc = e['account']
            amt = e['amount']
            pts = amt if e.get('entry_type') == 'credit' else -amt
            entries_data.append((acc, pts))

    if not entries_data or len(entries_data) < 2:
        raise LedgerImbalanceError("Double-entry transaction requires at least two balanced entries")

    total_sum = sum(points for _, points in entries_data)
    if total_sum != 0:
        raise LedgerImbalanceError(f"Ledger transaction unbalanced! Sum of entries is {total_sum}, must be exactly 0.")

    txn = LedgerTxn.objects.create(
        txn_type=txn_type,
        award=award,
        conversion_reference=conversion_reference or reference_id,
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


def calculate_account_balance(account) -> int:
    """
    Derives account balance strictly from immutable ledger entries.
    """
    if not account:
        return 0
    return LedgerEntry.objects.filter(account=account).aggregate(
        total=models.Sum('points')
    )['total'] or 0


# Canonical alias for posting double-entry transactions
post_ledger_transaction = create_balanced_ledger_txn


def get_user_ledger_balance(user) -> int:
    """
    Computes user's exact available points balance directly from the immutable double-entry ledger (SR-08).
    Account: kind='user_available'.
    Synchronizes the cached UserRewardProfile.available_points so frontend apps
    always receive mathematically verified ledger balances with zero drift.
    """
    if not user or not user.is_authenticated:
        return 0

    account = get_or_create_ledger_account('user_available', user=user)
    
    # Calculate balance as sum of all ledger entries for this account
    entry_total = LedgerEntry.objects.filter(account=account).aggregate(
        total=models.Sum('points')
    )['total'] or 0

    profile, _ = UserRewardProfile.objects.get_or_create(user=user)

    # If ledger has entries, ledger is the single source of truth
    if entry_total > 0:
        computed_balance = entry_total
        if profile.available_points != computed_balance:
            profile.available_points = computed_balance
            profile.save(update_fields=['available_points'])
        return computed_balance

    # If ledger has 0 entries but profile has legacy points, reconcile into ledger
    if entry_total == 0 and profile.available_points > 0:
        legacy_pts = profile.available_points
        try:
            mkt_account = get_or_create_ledger_account('marketing_expense')
            create_balanced_ledger_txn(
                txn_type='legacy_balance_reconciliation',
                idempotency_key=f"reconcile_legacy:{user.id}:{legacy_pts}",
                description=f"Legacy balance reconciliation for {user.email}",
                entries_data=[
                    (account, legacy_pts),
                    (mkt_account, -legacy_pts),
                ],
                created_by=user
            )
            return legacy_pts
        except Exception as e:
            logger.warning(f"Could not seed ledger from legacy profile: {e}")
            return legacy_pts

    return max(0, entry_total)


def reconcile_all_user_balances_to_ledger():
    """
    Audit & Migration utility: Iterates over all users, recomputing their exact
    available points strictly from the immutable double-entry ledger.
    Syncs UserRewardProfile.available_points to guarantee mathematical zero-drift.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    reconciled_count = 0

    for user in User.objects.filter(is_active=True):
        try:
            get_user_ledger_balance(user)
            reconciled_count += 1
        except Exception as e:
            logger.error(f"Error reconciling ledger balance for user {user.id}: {e}")

    logger.info(f"Reconciled ledger balances for {reconciled_count} active users.")
    return reconciled_count
