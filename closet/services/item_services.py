import logging
from typing import Optional, Tuple
from django.db import models
from django.utils import timezone
from django.conf import settings

from closet.models import ClosetItem

logger = logging.getLogger(__name__)


def record_wear_today(user, item_id: int) -> Tuple[bool, Optional[ClosetItem]]:
    """
    Atomically increments times_worn counter using F() expressions and updates last_worn_at.
    """
    try:
        item = ClosetItem.objects.get(pk=item_id, user=user)
        ClosetItem.objects.filter(pk=item_id, user=user).update(
            times_worn=models.F('times_worn') + 1,
            last_worn_at=timezone.now()
        )
        item.refresh_from_db()
        return True, item
    except ClosetItem.DoesNotExist:
        return False, None


def handle_item_creation_rewards_and_notifications(user, item: ClosetItem) -> None:
    """
    Awards gamified points and dispatches push notifications upon wardrobe item creation.
    """
    try:
        from rewards.services import award_points
        from rewards.models import RewardPointTransaction
        daily_awards = RewardPointTransaction.objects.filter(
            user=user,
            action_type='add_closet_item',
            created_at__date=timezone.now().date()
        ).count()
        limit = getattr(settings, 'MYC_CLOSET_ITEM_POINTS_DAILY_LIMIT', 10)
        if daily_awards < limit:
            award_points(
                user=user,
                action_type='add_closet_item',
                description=f"Added '{item.name}' to closet",
                reference_id=str(item.id)
            )
    except Exception as e:
        logger.warning(f"Error awarding points for adding closet item: {e}")

    try:
        from notifications.services import create_notification
        create_notification(
            recipient=user,
            notification_type='closet_item_added',
            title='Closet Item Added',
            message=f"'{item.name}' has been added to your digital wardrobe!",
            data={'item_id': item.id, 'category': item.category}
        )
    except Exception as e:
        logger.debug(f"Error creating closet item notification: {e}")


def get_filtered_closet_items(user, query_params) -> models.QuerySet:
    """
    Constructs an optimized queryset for the user's wardrobe items with filter parameters.
    """
    queryset = ClosetItem.objects.filter(user=user)
    category = query_params.get('category')
    color = query_params.get('color')
    brand = query_params.get('brand')

    if category:
        queryset = queryset.filter(category=category)
    if color:
        queryset = queryset.filter(color__icontains=color)
    if brand:
        queryset = queryset.filter(brand__icontains=brand)

    return queryset
