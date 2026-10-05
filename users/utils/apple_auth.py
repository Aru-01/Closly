import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def revoke_apple_token(user):
    """
    Revokes Apple authorization for the user via Apple's /auth/revoke endpoint.
    Complies with Apple App Store Review Guideline 5.1.1(v) for account deletion.
    """
    client_id = getattr(settings, 'APPLE_CLIENT_ID', None)
    client_secret = getattr(settings, 'APPLE_CLIENT_SECRET', None)

    # If Apple credentials are not configured, log gracefully and return
    if not client_id or not client_secret:
        logger.info(f"Apple client credentials not configured; skipping remote Apple revocation for user {user.id}.")
        return False

    refresh_token = getattr(user, 'apple_refresh_token', None)
    if not refresh_token:
        logger.info(f"No stored Apple refresh token for user {user.id}; skipping Apple token revocation.")
        return False

    try:
        url = "https://appleid.apple.com/auth/revoke"
        payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'token': refresh_token,
            'token_type_hint': 'refresh_token',
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info(f"Successfully revoked Apple token for user {user.id}.")
            return True
        else:
            logger.warning(f"Apple token revocation returned status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.warning(f"Failed to revoke Apple token for user {user.id}: {e}")
        return False
