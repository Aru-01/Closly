from django.urls import path
from .views import (
    AffiliateProductNewsfeedView,
    AffiliateProductDetailView,
    ProductClickView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
    AffiliateProductForYouView,
    ProductFavoriteToggleView,
    SavedProductsListView,
    EventBatchView,
    AwinWebhookView,
    StyleSprintView,
    StyleSprintSwipeView,
)

app_name = 'affiliate'

urlpatterns = [
    # Style Sprint (Daily 10-card fashion swipe deck)
    path('sprint/', StyleSprintView.as_view(), name='style-sprint'),
    path('sprint/swipe/', StyleSprintSwipeView.as_view(), name='style-sprint-swipe'),
    path('sprint/swipes/', StyleSprintSwipeView.as_view(), name='style-sprint-swipes'),

    # AWIN transaction webhook / postback
    path('webhooks/awin/', AwinWebhookView.as_view(), name='webhook-awin'),

    # User behavior event batch ingestion
    path('events/batch/', EventBatchView.as_view(), name='events-batch'),

    # Personalized 'For You' product feed based on user Style DNA
    path('products/for-you/', AffiliateProductForYouView.as_view(), name='products-for-you'),

    # Wishlist (Canonical REST: /products/favorites/)
    path('products/favorites/', SavedProductsListView.as_view(), name='products-favorites'),

    # Newsfeed — paginated product list with filters
    path('products/', AffiliateProductNewsfeedView.as_view(), name='products-feed'),

    # Single product detail (full info + affiliate link)
    path('products/<int:pk>/', AffiliateProductDetailView.as_view(), name='product-detail'),

    # Favorite toggle (Canonical REST: /products/<pk>/favorite/)
    path('products/<int:pk>/favorite/', ProductFavoriteToggleView.as_view(), name='product-favorite'),

    # Click tracking — call before opening the affiliate link
    path('products/<int:pk>/click/', ProductClickView.as_view(), name='product-click'),

    # Filter helpers
    path('brands/', AffiliateBrandsListView.as_view(), name='brands-list'),
    path('categories/', AffiliateCategoriesListView.as_view(), name='categories-list'),
]
