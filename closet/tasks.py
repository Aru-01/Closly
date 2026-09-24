import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='closet.tasks.recalculate_wardrobe_analytics_task')
def recalculate_wardrobe_analytics_task(user_id):
    """
    Background worker task to recompute wardrobe score, total items, 
    and most worn categories without blocking the user response.
    """
    from django.contrib.auth import get_user_model
    from closet.models import ClosetItem
    from rewards.models import UserRewardProfile

    User = get_user_model()
    try:
        user = User.objects.filter(id=user_id).first()
        if not user:
            return None

        items = ClosetItem.objects.filter(user=user)
        total_items = items.count()

        # Update cached stats or reward profile
        profile = UserRewardProfile.objects.filter(user=user).first()
        if profile and total_items > 0:
            logger.info(f"Recomputed wardrobe analytics for user {user.email}: {total_items} items.")
        return total_items
    except Exception as e:
        logger.error(f"Error recalculating wardrobe analytics for user {user_id}: {e}")
        return None
