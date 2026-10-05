"""
Users app configuration
"""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """
    Configuration for users app
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    verbose_name = 'User Management'
    
    def ready(self):
        """
        Initialize app when Django starts
        This is called once when Django loads the app
        """
        # Import and initialize Firebase Admin SDK
        try:
            from .utils import initialize_firebase
            initialize_firebase()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning: Failed to initialize Firebase: {str(e)}")
            logger.warning("Firebase authentication will not be available.")
        
        # Import drf-spectacular schema extensions
        try:
            from . import schema
        except ImportError as e:
            logger.warning(f"drf-spectacular schema extensions not found: {str(e)}")

        # Connect pre_delete media file cleanup signals for GDPR storage erasure
        try:
            from .signals import register_media_cleanup_signals
            register_media_cleanup_signals()
        except Exception as e:
            logger.warning(f"Failed to register media cleanup signals: {e}")