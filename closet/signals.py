import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import ClosetItem, FitCheck

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=ClosetItem)
def cleanup_closet_item_image_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when a ClosetItem is deleted, its image file is safely purged from storage
    if no other ClosetItem references the exact same image path.
    """
    if instance.image and hasattr(instance.image, 'storage') and instance.image.name:
        storage = instance.image.storage
        path = instance.image.name
        try:
            if storage.exists(path):
                if not ClosetItem.objects.filter(image=path).exists():
                    storage.delete(path)
                    logger.info(f"Purged storage image for ClosetItem {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging image for ClosetItem {instance.id}: {e}")


@receiver(post_delete, sender=FitCheck)
def cleanup_fit_check_photo_on_post_delete(sender, instance, **kwargs):
    """
    Ensures that when a FitCheck audit record is deleted (e.g. GDPR deletion), its photo
    is safely removed from storage.
    """
    if instance.photo and hasattr(instance.photo, 'storage') and instance.photo.name:
        storage = instance.photo.storage
        path = instance.photo.name
        try:
            if storage.exists(path):
                storage.delete(path)
                logger.info(f"Purged storage photo for FitCheck {instance.id}: {path}")
        except Exception as e:
            logger.warning(f"Error purging photo for FitCheck {instance.id}: {e}")
