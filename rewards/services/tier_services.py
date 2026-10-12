import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def get_tier_thresholds():
    """
    Returns list of (TierName, LifetimePointThreshold) tuples.
    Thresholds:
      Bronze: 0 - 2,000
      Silver: 2,000 - 5,000
      Gold: 5,000 - 10,000
      Platinum: 10,000 - 50,000
      Diamond: 50,000+
    """
    return [
        ('Diamond', getattr(settings, 'MYC_TIER_DIAMOND_THRESHOLD', 50000)),
        ('Platinum', getattr(settings, 'MYC_TIER_PLATINUM_THRESHOLD', 10000)),
        ('Gold', getattr(settings, 'MYC_TIER_GOLD_THRESHOLD', 5000)),
        ('Silver', getattr(settings, 'MYC_TIER_SILVER_THRESHOLD', 2000)),
        ('Bronze', 0),
    ]

TIER_THRESHOLDS = get_tier_thresholds()


def get_action_points():
    """Returns baseline reward points awarded per domain action."""
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
