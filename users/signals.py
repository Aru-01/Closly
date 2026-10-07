import logging
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def _delete_file_safely(field_file):
    """
    Safely delete a storage file associated with a FieldFile/ImageFieldFile.
    """
    if field_file and hasattr(field_file, 'storage') and bool(field_file.name):
        try:
            if field_file.storage.exists(field_file.name):
                field_file.storage.delete(field_file.name)
                logger.info(f"Purged storage file: {field_file.name}")
        except Exception as e:
            logger.warning(f"Could not purge storage file {field_file.name}: {e}")


@receiver(pre_delete, sender=User)
def cleanup_user_avatar_file(sender, instance, **kwargs):
    _delete_file_safely(instance.profile_picture)


def register_media_cleanup_signals():
    """
    Connect pre_delete cleanup handlers for all media-storing models across apps.
    """
    try:
        from closet.models import ClosetItem, FitCheck
        @receiver(pre_delete, sender=ClosetItem, weak=False)
        def cleanup_closet_item_image(sender, instance, **kwargs):
            _delete_file_safely(instance.image)

        @receiver(pre_delete, sender=FitCheck, weak=False)
        def cleanup_fit_check_photo(sender, instance, **kwargs):
            _delete_file_safely(instance.photo)
    except Exception as e:
        logger.debug(f"Could not register ClosetItem/FitCheck media signal: {e}")


    try:
        from social.models import TodayOutfit, OutfitImage, Story, DirectMessage
        @receiver(pre_delete, sender=TodayOutfit, weak=False)
        def cleanup_today_outfit_image(sender, instance, **kwargs):
            _delete_file_safely(instance.image)

        @receiver(pre_delete, sender=OutfitImage, weak=False)
        def cleanup_outfit_image(sender, instance, **kwargs):
            _delete_file_safely(instance.image)

        @receiver(pre_delete, sender=Story, weak=False)
        def cleanup_story_image(sender, instance, **kwargs):
            _delete_file_safely(instance.image)

        @receiver(pre_delete, sender=DirectMessage, weak=False)
        def cleanup_direct_message_image(sender, instance, **kwargs):
            _delete_file_safely(instance.image)
    except Exception as e:
        logger.debug(f"Could not register social media signals: {e}")
