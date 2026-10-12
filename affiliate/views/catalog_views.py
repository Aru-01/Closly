import logging
from django.db.models import Count
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from affiliate.models import AffiliateProduct
from affiliate.serializers import (
    AffiliateProductListSerializer,
    AffiliateProductDetailSerializer,
)
from affiliate.services.catalog_services import (
    get_catalog_queryset,
    annotate_catalog_favorites,
    get_catalog_brands,
    get_catalog_categories,
)

logger = logging.getLogger(__name__)


class NewsfeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'success': True,
            'message': 'Products retrieved successfully',
            'data': {
                'count':    self.page.paginator.count,
                'next':     self.get_next_link(),
                'previous': self.get_previous_link(),
                'results':  data,
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Affiliate Products Feed",
    description="Returns paginated affiliate products for the newsfeed with search, brand, category, colour, price, discount sorting, and network filters.",
    parameters=[
        OpenApiParameter('search', str, description="Search across product name, brand, description"),
        OpenApiParameter('brand', str, description="Filter by brand (exact match)"),
        OpenApiParameter('category', str, description="Filter by product category"),
        OpenApiParameter('colour', str, description="Filter by colour keyword"),
        OpenApiParameter('min_price', float, description="Minimum price filter"),
        OpenApiParameter('max_price', float, description="Maximum price filter"),
        OpenApiParameter('ordering', str, description="Sort order: 'price_asc', 'price_desc', 'newest', 'discount'"),
        OpenApiParameter('source', str, description="Filter by network: 'awin', 'rakuten', 'shopify', 'myc_feed'"),
    ],
    responses={
        200: AffiliateProductListSerializer(many=True),
    }
)
class AffiliateProductNewsfeedView(generics.ListAPIView):
    """
    Skinny View: Lists and filters catalog products for the newsfeed.
    Delegates SQL construction and select_related('brand_ref') to catalog_services.
    GET /api/affiliate/products/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        return get_catalog_queryset(self.request.query_params)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            user_fav_ids = annotate_catalog_favorites(page, request.user)
            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Affiliate Product Details",
    description="Returns full product details including official tracked affiliate link, pricing, and brand metadata.",
    responses={
        200: AffiliateProductDetailSerializer,
        404: OpenApiResponse(description="Product not found"),
    }
)
class AffiliateProductDetailView(generics.RetrieveAPIView):
    """
    Skinny View: Product detail inspection.
    Uses select_related('brand_ref') to eliminate N+1 queries.
    GET /api/affiliate/products/<id>/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductDetailSerializer
    queryset = (
        AffiliateProduct.objects.filter(is_active=True)
        .select_related('brand_ref')
        .annotate(
            _favorites_count=Count('favorites', distinct=True),
            _clicks_count=Count('clicks', distinct=True),
        )
    )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Product retrieved successfully',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="List Affiliate Brands",
    description="Returns all unique brands and available product counts for filter dropdowns.",
    parameters=[
        OpenApiParameter('source', str, description="Filter by network: 'awin' or 'rakuten'"),
    ],
    responses={
        200: OpenApiResponse(description="List of available brands and product counts")
    }
)
class AffiliateBrandsListView(APIView):
    """
    Skinny View: Returns unique brands list for navigation.
    GET /api/affiliate/brands/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        source = request.query_params.get('source')
        brands = get_catalog_brands(source)
        return Response({
            'success': True,
            'message': 'Brands retrieved successfully',
            'data': {
                'brands': brands
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="List Affiliate Categories",
    description="Returns list of unique product categories with product counts for catalog navigation.",
    responses={
        200: OpenApiResponse(description="List of categories and item counts")
    }
)
class AffiliateCategoriesListView(APIView):
    """
    Skinny View: Returns unique categories list for navigation.
    GET /api/affiliate/categories/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        categories = get_catalog_categories()
        return Response({
            'success': True,
            'message': 'Categories retrieved successfully',
            'data': {
                'categories': categories
            }
        }, status=status.HTTP_200_OK)
