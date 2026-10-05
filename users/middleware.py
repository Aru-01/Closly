import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class UserActivityMiddleware(MiddlewareMixin):
    """
    Middleware to automatically record user activity and maintain real-time online status
    whenever an authenticated user interacts with any Closly API endpoint.
    """
    def process_response(self, request, response):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            try:
                from users.utils import set_user_online
                set_user_online(str(user.id))
            except Exception:
                pass
        return response