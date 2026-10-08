import urllib.parse
import logging
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from django.core.cache import cache

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def get_user_from_token(token_key):
    try:
        access_token = AccessToken(token_key)
        user_id = access_token.get('user_id')
        if user_id:
            return User.objects.get(id=user_id, is_active=True)
    except Exception as e:
        logger.debug(f"WebSocket JWT Auth failed: {e}")
    return AnonymousUser()


def get_user_from_ticket_sync(ticket):
    """
    Resolves and atomically consumes a 60-second single-use ticket (SR-09).
    Prevents token leakage in access logs and eliminates race conditions
    via atomic mutex reservation (cache.add SETNX).
    """
    if not ticket or not isinstance(ticket, str) or not ticket.startswith('wst_') or len(ticket) > 64:
        return AnonymousUser()

    lock_key = f"ws_ticket_lock:{ticket}"
    # Atomic reservation: Only the first concurrent connection acquires this lock.
    acquired = cache.add(lock_key, "1", timeout=10)
    if not acquired:
        logger.warning(f"Concurrent or replayed WebSocket ticket attempt rejected: {ticket}")
        return AnonymousUser()

    cache_key = f"ws_ticket:{ticket}"
    try:
        user_id = cache.get(cache_key)
        if user_id:
            cache.delete(cache_key)  # Strictly single-use!
            try:
                return User.objects.get(id=user_id, is_active=True)
            except Exception:
                return AnonymousUser()
        return AnonymousUser()
    except Exception as e:
        logger.error(f"Error resolving WebSocket ticket {ticket}: {e}")
        return AnonymousUser()


get_user_from_ticket = database_sync_to_async(get_user_from_ticket_sync)


class JWTAuthMiddleware:
    """
    Custom WebSocket middleware authenticating users exclusively via:
    1. Short-lived 60-second single-use ticket (?ticket=<ticket>) (SR-09).
    2. Sec-WebSocket-Protocol header (closly-auth.<ticket>).

    Raw JWT access tokens (?token=<jwt>) are strictly REJECTED to prevent
    bearer token exposure in server logs, proxy histories, and URLs.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = urllib.parse.parse_qs(query_string)

        # 1. Single-use ticket from query parameters
        ticket = query_params.get("ticket", [None])[0]

        # 2. Check Sec-WebSocket-Protocol header (closly-auth.<ticket>)
        headers = dict(scope.get("headers", []))
        ws_protocol = headers.get(b"sec-websocket-protocol", b"").decode("utf-8")
        if ws_protocol:
            protocols = [p.strip() for p in ws_protocol.split(",")]
            for proto in protocols:
                if proto.startswith("closly-auth."):
                    auth_val = proto.split("closly-auth.", 1)[1].strip()
                    # Only short-lived ticket format accepted (wst_ prefix, <= 64 chars). Raw JWTs rejected!
                    if auth_val.startswith("wst_") and len(auth_val) <= 64:
                        ticket = auth_val
                        scope["subprotocol"] = proto
                        break

        # Authenticate strictly via ticket
        if ticket:
            user = await get_user_from_ticket(ticket)
            if user and user.is_authenticated:
                scope["user"] = user
            else:
                scope["user"] = AnonymousUser()
        else:
            # Missing or unsupported credential format (e.g. raw ?token=<jwt>)
            scope["user"] = AnonymousUser()

        return await self.inner(scope, receive, send)
