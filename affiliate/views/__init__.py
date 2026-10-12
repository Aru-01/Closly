"""
Affiliate views package.
Re-exports all modular views across discovery, catalog, sprint, telemetry,
favorites, and webhooks to maintain 100% backward compatibility.
"""

from .discovery_views import (
    ForYouPagination,
    AffiliateProductForYouView,
)

from .catalog_views import (
    NewsfeedPagination,
    AffiliateProductNewsfeedView,
    AffiliateProductDetailView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
)

from .product_views import (
    ProductClickView,
    build_affiliate_url,
)

from .sprint_views import (
    StyleSprintView,
    StyleSprintSwipeView,
)

from .telemetry_views import (
    EventBatchView,
)

from .favorite_views import (
    ProductFavoriteToggleView,
    SavedProductsListView,
)

from .webhook_views import (
    AwinWebhookView,
)

__all__ = [
    'NewsfeedPagination',
    'ForYouPagination',
    'AffiliateProductNewsfeedView',
    'AffiliateProductForYouView',
    'AffiliateProductDetailView',
    'ProductClickView',
    'AffiliateBrandsListView',
    'AffiliateCategoriesListView',
    'build_affiliate_url',
    'ProductFavoriteToggleView',
    'SavedProductsListView',
    'EventBatchView',
    'AwinWebhookView',
    'StyleSprintView',
    'StyleSprintSwipeView',
]
