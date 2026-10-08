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
    if instance.profile_picture and hasattr(instance.profile_picture, 'storage') and bool(instance.profile_picture.name):
        try:
            if instance.profile_picture.storage.exists(instance.profile_picture.name):
                # Only delete if no other user references the same avatar file
                if not User.objects.filter(profile_picture=instance.profile_picture.name).exclude(pk=instance.pk).exists():
                    instance.profile_picture.storage.delete(instance.profile_picture.name)
                    logger.info(f"Purged storage file: {instance.profile_picture.name}")
        except Exception as e:
            logger.warning(f"Could not purge user avatar file {instance.profile_picture.name}: {e}")


def register_media_cleanup_signals():
    """
    Ensures media cleanup signals across apps are properly registered.
    Closet and Social media signals are independently registered via closet.signals and social.signals.
    """
    pass
