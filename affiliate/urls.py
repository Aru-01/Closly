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
)

app_name = 'affiliate'

urlpatterns = [
    # Personalized 'For You' product feed based on user Style DNA
    path('products/for-you/', AffiliateProductForYouView.as_view(), name='products-for-you'),

    # Saved / Loved products wishlist
    path('products/saved/', SavedProductsListView.as_view(), name='products-saved'),
    path('products/favorites/', SavedProductsListView.as_view(), name='products-favorites'),

    # Newsfeed — paginated product list with filters
    path('products/', AffiliateProductNewsfeedView.as_view(), name='products-feed'),

    # Single product detail (full info + affiliate link)
    path('products/<int:pk>/', AffiliateProductDetailView.as_view(), name='product-detail'),

    # Love / Save (Wishlist toggle)
    path('products/<int:pk>/love/', ProductFavoriteToggleView.as_view(), name='product-love'),
    path('products/<int:pk>/favorite/', ProductFavoriteToggleView.as_view(), name='product-favorite'),
    path('products/<int:pk>/save/', ProductFavoriteToggleView.as_view(), name='product-save'),

    # Click tracking — call before opening the affiliate link
    path('products/<int:pk>/click/', ProductClickView.as_view(), name='product-click'),

    # Filter helpers
    path('brands/', AffiliateBrandsListView.as_view(), name='brands-list'),
    path('categories/', AffiliateCategoriesListView.as_view(), name='categories-list'),
]
