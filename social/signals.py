import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import TodayOutfit, OutfitImage, Story, DirectMessage

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=TodayOutfit)
def cleanup_today_outfit_image_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when a TodayOutfit is deleted:
    1. Any earned activity reward is safely reversed in the double-entry ledger (SR-07).
    2. Tagged items' times_worn counters are decremented (SR-26).
    3. Primary image file is purged from storage (SR-11).
    """
    # 1. Reverse activity points in double-entry ledger
    try:
        from rewards.services import reverse_activity_reward
        reverse_activity_reward(user=instance.user, outfit_id=instance.id)
    except Exception as e:
        logger.warning(f"Error reversing activity reward on TodayOutfit {instance.id} delete: {e}")

    # 2. Revert times_worn on tagged items
    try:
        for item in instance.tagged_items.all():
            if item.times_worn > 0:
                item.times_worn = item.times_worn - 1
                item.save(update_fields=['times_worn'])
    except Exception as e:
        logger.warning(f"Error reverting times_worn for TodayOutfit {instance.id}: {e}")

    # 3. Purge storage image
    if instance.image and hasattr(instance.image, 'storage') and instance.image.name:
        storage = instance.image.storage
        path = instance.image.name
        try:
            if storage.exists(path):
                if not TodayOutfit.objects.filter(image=path).exists():
                    storage.delete(path)
                    logger.info(f"Purged storage image for TodayOutfit {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging image for TodayOutfit {instance.id}: {e}")


@receiver(post_delete, sender=OutfitImage)
def cleanup_outfit_image_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when an OutfitImage carousel item is deleted, its image file is purged from storage.
    """
    if instance.image and hasattr(instance.image, 'storage') and instance.image.name:
        storage = instance.image.storage
        path = instance.image.name
        try:
            if storage.exists(path):
                if not OutfitImage.objects.filter(image=path).exists() and not TodayOutfit.objects.filter(image=path).exists():
                    storage.delete(path)
                    logger.info(f"Purged storage carousel image for OutfitImage {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging carousel image for OutfitImage {instance.id}: {e}")


@receiver(post_delete, sender=Story)
def cleanup_story_image_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when a Story is deleted, its image file is purged from storage.
    """
    if instance.image and hasattr(instance.image, 'storage') and instance.image.name:
        storage = instance.image.storage
        path = instance.image.name
        try:
            if storage.exists(path):
                if not Story.objects.filter(image=path).exists():
                    storage.delete(path)
                    logger.info(f"Purged storage image for Story {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging image for Story {instance.id}: {e}")


@receiver(post_delete, sender=DirectMessage)
def cleanup_direct_message_image_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when a DirectMessage is deleted, any attached image file is purged from storage.
    """
    if instance.image and hasattr(instance.image, 'storage') and instance.image.name:
        storage = instance.image.storage
        path = instance.image.name
        try:
            if storage.exists(path):
                if not DirectMessage.objects.filter(image=path).exists():
                    storage.delete(path)
                    logger.info(f"Purged storage attachment for DirectMessage {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging attachment for DirectMessage {instance.id}: {e}")
