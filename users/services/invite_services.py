import secrets
import logging
from typing import Tuple, List, Optional
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from users.models import Invite
from users.utils.error_codes import (
    INVITE_INVALID,
    INVITE_ALREADY_USED,
    INVITE_EXPIRED,
)

logger = logging.getLogger(__name__)


def get_or_create_user_invites(user, quota: int = 5) -> List[Invite]:
    """
    Returns up to `quota` single-use invite codes for the specified user.
    If fewer than `quota` codes exist, auto-generates unique standard codes up to quota.
    """
    existing_invites = list(Invite.objects.filter(owner_user=user).order_by('created_at')[:quota])
    current_count = len(existing_invites)

    if current_count < quota:
        new_invites = []
        for _ in range(quota - current_count):
            for _attempt in range(10):
                candidate_code = f"CLO-{secrets.token_hex(4).upper()}"
                if not Invite.objects.filter(code=candidate_code).exists():
                    inv = Invite.objects.create(
                        code=candidate_code,
                        kind='standard',
                        owner_user=user,
                    )
                    new_invites.append(inv)
                    break
        existing_invites.extend(new_invites)

    return existing_invites[:quota]


def redeem_invite_code(user, raw_code: str) -> Tuple[bool, Optional[dict], Optional[str], Optional[str]]:
    """
    Validates and claims a single-use invite code for the given user.

    Returns:
        (success, data_dict, error_message, error_code)
    """
    code_str = (raw_code or '').strip().upper()

    # Check if user already claimed an invite
    if Invite.objects.filter(used_by=user).exists():
        return False, None, 'You have already redeemed an invite code.', 'INVITE_ALREADY_CLAIMED'

    # Check bypass codes (e.g. TestFlight or App Store review)
    bypass_codes = getattr(settings, 'MYC_INVITE_BYPASS_CODES', ['APPLE_REVIEW', 'TESTFLIGHT_BETA'])
    if code_str in bypass_codes:
        return True, {
            'code': code_str,
            'kind': 'review',
            'used_at': timezone.now(),
        }, None, None

    invite = Invite.objects.filter(code=code_str).first()
    if not invite:
        return False, None, 'Invalid invite code.', INVITE_INVALID

    if invite.owner_user_id == user.id:
        return False, None, 'You cannot redeem an invite code that you own.', 'INVITE_SELF_REDEEM_NOT_ALLOWED'

    if not invite.is_valid():
        if invite.used_by_id or invite.used_at:
            return False, None, 'This invite code has already been claimed.', INVITE_ALREADY_USED
        if invite.expires_at and timezone.now() > invite.expires_at:
            return False, None, 'This invite code has expired.', INVITE_EXPIRED

    with transaction.atomic():
        locked_invite = Invite.objects.select_for_update().get(id=invite.id)
        if locked_invite.used_by_id is not None or locked_invite.used_at is not None:
            return False, None, 'This invite code has already been claimed.', INVITE_ALREADY_USED

        locked_invite.used_by = user
        locked_invite.used_at = timezone.now()
        locked_invite.save(update_fields=['used_by', 'used_at'])

    logger.info(f"User {user.id} ({user.email}) successfully redeemed invite code {locked_invite.code}")

    return True, {
        'code': locked_invite.code,
        'kind': locked_invite.kind,
        'used_at': locked_invite.used_at,
    }, None, None
