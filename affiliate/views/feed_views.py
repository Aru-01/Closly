"""
affiliate/views/feed_views.py
Modularized re-export façade:
- Newsfeed views & pagination moved to `catalog_views.py`.
- For-You feed views & pagination moved to `discovery_views.py`.
- Feed candidates & ranking algorithms moved to `affiliate.services.discovery_services`.
"""

from .catalog_views import (
    NewsfeedPagination,
    AffiliateProductNewsfeedView,
)

from .discovery_views import (
    ForYouPagination,
    AffiliateProductForYouView,
)

__all__ = [
    'NewsfeedPagination',
    'ForYouPagination',
    'AffiliateProductNewsfeedView',
    'AffiliateProductForYouView',
]
