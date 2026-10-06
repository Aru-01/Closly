import hashlib
from rest_framework.throttling import SimpleRateThrottle
from django.conf import settings


class ProductClickRateThrottle(SimpleRateThrottle):
    """
    Limits outbound product click requests to prevent click-fraud, affiliate scraping,
    and denial-of-service on attribution tracking.
    Target rate: 30 clicks/hour/user (configurable via MYC_CLICK_THROTTLE_RATE).
    """
    scope = 'product_click'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = f"user_{request.user.pk}"
        else:
            session_id = (
                request.headers.get('X-Session-ID')
                or request.data.get('session_id')
                or request.query_params.get('session_id')
            )
            if session_id:
                ident = f"session_{session_id}"
            else:
                ident = f"ip_{self.get_ident(request)}"
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }


class EventBatchRateThrottle(SimpleRateThrottle):
    """
    Limits event batch submission endpoint.
    Default: 120/min.
    """
    scope = 'events_batch'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = f"user_{request.user.pk}"
        else:
            ident = f"ip_{self.get_ident(request)}"
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }
