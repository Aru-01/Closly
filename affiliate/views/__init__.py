"""
Affiliate views package. Re-exports all views to maintain 100% backward compatibility.
"""

from .feed_views import (
    NewsfeedPagination,
    ForYouPagination,
    AffiliateProductNewsfeedView,
    AffiliateProductForYouView,
)

from .product_views import (
    AffiliateProductDetailView,
    ProductClickView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
    build_affiliate_url,
)

from .favorite_views import (
    ProductFavoriteToggleView,
    SavedProductsListView,
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
]
