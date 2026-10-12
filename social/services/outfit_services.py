import logging
from django.db import transaction
from django.utils import timezone
from social.models import TodayOutfit, OutfitLike, OutfitImage
from rewards.services import award_points

logger = logging.getLogger(__name__)


def toggle_outfit_like(user, outfit_id: int):
    """
    Toggles like status for an outfit in an atomic, idempotent operation.
    Returns (outfit, is_liked, current_like_count).
    """
    with transaction.atomic():
        outfit = TodayOutfit.objects.select_for_update().get(id=outfit_id)
        like = OutfitLike.objects.filter(user=user, outfit=outfit).first()
        if like:
            like.delete()
            is_liked = False
        else:
            OutfitLike.objects.create(user=user, outfit=outfit)
            is_liked = True

        likes_count = OutfitLike.objects.filter(outfit=outfit).count()
        return outfit, is_liked, likes_count


def handle_outfit_creation_rewards(user, outfit: TodayOutfit):
    """
    Awards loyalty points for sharing a look and updates wear timestamps on tagged garments.
    """
    try:
        award_points(user=user, action_type='share_look', reference_id=str(outfit.id))
    except Exception as e:
        logger.warning(f"Could not award points for outfit #{outfit.id}: {e}")

    # Update wear counters on tagged closet items
    try:
        now = timezone.now()
        for item in outfit.tagged_items.all():
            item.times_worn += 1
            item.last_worn_at = now
            item.save(update_fields=['times_worn', 'last_worn_at'])
    except Exception as e:
        logger.warning(f"Could not update wear counters for tagged items on outfit #{outfit.id}: {e}")
