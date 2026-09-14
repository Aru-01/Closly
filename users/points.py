"""
Backward-compatibility proxy for rewards and gamification services.
Points and rewards logic has been moved to the dedicated `rewards` Django app.
"""
from rewards.services import (
    award_points,
    get_tier_for_points,
    get_tier_info,
    process_expired_points,
    TIER_THRESHOLDS,
    ACTION_POINTS,
    POINT_VALIDITY_DAYS,
)

__all__ = [
    'award_points',
    'get_tier_for_points',
    'get_tier_info',
    'process_expired_points',
    'TIER_THRESHOLDS',
    'ACTION_POINTS',
    'POINT_VALIDITY_DAYS',
]
