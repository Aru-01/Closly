import logging
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

logger = logging.getLogger(__name__)


def revoke_all_user_tokens(user):
    """
    Revokes (blacklists) all outstanding refresh tokens for a user.
    Executed during password reset, password change, or account deletion.
    """
    if not user:
        return 0

    revoked_count = 0
    try:
        outstanding_tokens = OutstandingToken.objects.filter(user=user)
        for token in outstanding_tokens:
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                revoked_count += 1
        logger.info(f"Revoked {revoked_count} outstanding token(s) for user {getattr(user, 'email', user.id)}")
    except Exception as e:
        logger.warning(f"Error revoking tokens for user {getattr(user, 'id', '')}: {e}")

    return revoked_count
