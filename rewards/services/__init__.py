"""
Rewards Services Package.
Domain-Driven Design (DDD) modular service architecture for the rewards domain:
- tier_services: Tier thresholds, validity periods, status progressions.
- ledger_services: Strict double-entry financial ledger math, balance derivations.
- award_services: PointAward state machine transitions, expirations, reconciliations.
- activity_services: Daily outfit activity awards, reversals, referral lifecycle.
"""

from .tier_services import (
    get_tier_thresholds,
    TIER_THRESHOLDS,
    get_action_points,
    ACTION_POINTS,
    get_point_validity_days,
    get_tier_for_lifetime_points,
    get_tier_info,
)

from .ledger_services import (
    LedgerImbalanceError,
    get_or_create_ledger_account,
    get_user_ledger_balance,
    create_balanced_ledger_txn,
    calculate_account_balance,
    post_ledger_transaction,
    reconcile_all_user_balances_to_ledger,
)

from .award_services import (
    transition_award,
    award_points,
    process_expired_points,
    reconcile_existing_reward_data,
)

from .activity_services import (
    record_activity_reward,
    reverse_activity_reward,
    activate_referral_reward,
    record_pending_referral_reward,
)

__all__ = [
    # Tier Services
    'get_tier_thresholds',
    'TIER_THRESHOLDS',
    'get_action_points',
    'ACTION_POINTS',
    'get_point_validity_days',
    'get_tier_for_lifetime_points',
    'get_tier_info',
    # Ledger Services
    'LedgerImbalanceError',
    'get_or_create_ledger_account',
    'get_user_ledger_balance',
    'create_balanced_ledger_txn',
    'calculate_account_balance',
    'post_ledger_transaction',
    'reconcile_all_user_balances_to_ledger',
    # Award Services
    'transition_award',
    'award_points',
    'process_expired_points',
    'reconcile_existing_reward_data',
    # Activity Services
    'record_activity_reward',
    'reverse_activity_reward',
    'activate_referral_reward',
    'record_pending_referral_reward',
]
