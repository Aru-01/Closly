"""
Closet services package.
Provides AI vision scanning, wardrobe analytics, item wear management, and NSFW safety pre-screening.
"""

from .ai_vision_services import (
    handle_fit_check_submission,
    get_fit_check_details,
    ConsentRequiredError,
    TaskQueueUnavailableError,
)

from .analytics_services import (
    get_wardrobe_analytics,
)

from .item_services import (
    record_wear_today,
    handle_item_creation_rewards_and_notifications,
    get_filtered_closet_items,
)

from .safety_services import (
    evaluate_and_enforce_image_safety,
    evaluate_image_safety,
    local_heuristic_nsfw_analysis,
    NsfwContentDetectedError,
)

__all__ = [
    'handle_fit_check_submission',
    'get_fit_check_details',
    'ConsentRequiredError',
    'TaskQueueUnavailableError',
    'get_wardrobe_analytics',
    'record_wear_today',
    'handle_item_creation_rewards_and_notifications',
    'get_filtered_closet_items',
    'evaluate_and_enforce_image_safety',
    'evaluate_image_safety',
    'local_heuristic_nsfw_analysis',
    'NsfwContentDetectedError',
]
