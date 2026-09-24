import logging
from django.conf import settings
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

logger = logging.getLogger(__name__)


def initialize_firebase():
    """
    Initialize Firebase Admin SDK with service account credentials.
    This should be called once when Django starts.
    """
    if not firebase_admin._apps:
        firebase_credentials_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
        if not firebase_credentials_path:
            logger.warning("Warning: FIREBASE_CREDENTIALS_PATH is not set in settings. Firebase Admin SDK will not be initialized.")
            return

        cred = credentials.Certificate(firebase_credentials_path)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized successfully")


def verify_firebase_token(id_token):
    """
    Verify Firebase ID token and return decoded token data.
    
    Args:
        id_token (str): Firebase ID token from client
        
    Returns:
        dict: Decoded token data with user info
        
    Raises:
        Exception: If token is invalid or expired
    """
    try:
        decoded_token = firebase_auth.verify_id_token(id_token, clock_skew_seconds=5)
        return decoded_token
    except Exception as e:
        raise Exception(f"Invalid Firebase token: {str(e)}")
