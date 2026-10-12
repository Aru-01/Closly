from django.urls import path

from .views.sprint_views import (
    StyleSprintView,
    StyleSprintSwipeView,
)
from .views.webhook_views import (
    AwinWebhookView,
)
from .views.telemetry_views import (
    EventBatchView,
)
from .views.discovery_views import (
    AffiliateProductForYouView,
)
from .views.favorite_views import (
    ProductFavoriteToggleView,
    SavedProductsListView,
)
from .views.catalog_views import (
    AffiliateProductNewsfeedView,
    AffiliateProductDetailView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
)
from .views.product_views import (
    ProductClickView,
)

app_name = 'affiliate'

urlpatterns = [
    # Style Sprint (Daily 10-card fashion swipe deck)
    path('sprint/', StyleSprintView.as_view(), name='style-sprint'),
    path('sprint/swipe/', StyleSprintSwipeView.as_view(), name='style-sprint-swipe'),

    # AWIN transaction webhook / postback
    path('webhooks/awin/', AwinWebhookView.as_view(), name='webhook-awin'),

    # User behavior event batch ingestion (Telemetry)
    path('events/batch/', EventBatchView.as_view(), name='events-batch'),

    # Personalized 'For You' product feed based on user Style DNA
    path('products/for-you/', AffiliateProductForYouView.as_view(), name='products-for-you'),

    # Wishlist (Saved / Loved Products)
    path('products/favorites/', SavedProductsListView.as_view(), name='products-favorites'),

    # Newsfeed — paginated product catalog with filters
    path('products/', AffiliateProductNewsfeedView.as_view(), name='products-feed'),

    # Single product detail (full info + affiliate link)
    path('products/<int:pk>/', AffiliateProductDetailView.as_view(), name='product-detail'),

    # Favorite toggle
    path('products/<int:pk>/favorite/', ProductFavoriteToggleView.as_view(), name='product-favorite'),

    # Click tracking — call before opening the affiliate link
    path('products/<int:pk>/click/', ProductClickView.as_view(), name='product-click'),

    # Filter helpers
    path('brands/', AffiliateBrandsListView.as_view(), name='brands-list'),
    path('categories/', AffiliateCategoriesListView.as_view(), name='categories-list'),
]
