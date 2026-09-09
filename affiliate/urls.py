from django.urls import path
from .views import (
    AffiliateProductNewsfeedView,
    AffiliateProductDetailView,
    ProductClickView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
)

app_name = 'affiliate'

urlpatterns = [
    # Newsfeed — paginated product list with filters
    path('products/', AffiliateProductNewsfeedView.as_view(), name='products-feed'),

    # Single product detail (full info + affiliate link)
    path('products/<int:pk>/', AffiliateProductDetailView.as_view(), name='product-detail'),

    # Click tracking — call before opening the affiliate link
    path('products/<int:pk>/click/', ProductClickView.as_view(), name='product-click'),

    # Filter helpers
    path('brands/', AffiliateBrandsListView.as_view(), name='brands-list'),
    path('categories/', AffiliateCategoriesListView.as_view(), name='categories-list'),
]
