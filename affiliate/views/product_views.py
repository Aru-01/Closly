from urllib.parse import quote
from django.conf import settings
from django.db.models import Count
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductClick
from affiliate.serializers import AffiliateProductDetailSerializer

_APP_LINK_DOMAINS = (
    'onelink.me',       # AppsFlyer OneLink
    'app.link',         # Branch.io
    'go.onelink.me',
    'bnc.lt',           # Branch short links
    'adj.st',           # Adjust
    'smart.link',       # Smartly / Kochava
    'play.google.com',  # Google Play store
    'apps.apple.com',   # Apple App Store
    'itunes.apple.com',
)


def _is_usable_web_url(url: str) -> bool:
    """
    Return True if `url` is a regular web URL that can be loaded in a browser.
    Returns False for mobile app deep links, app-store URLs, or empty strings.
    """
    if not url:
        return False
    url_lower = url.lower()
    if not url_lower.startswith(('http://', 'https://')):
        return False
    for domain in _APP_LINK_DOMAINS:
        if domain in url_lower:
            return False
    return True


def build_affiliate_url(product):
    """
    Build the correct affiliate tracking URL for a product.
    """
    raw_link = (product.aw_deep_link or '').strip()
    if raw_link.startswith(('http://', 'https://')):
        return raw_link

    merchant_link = (product.merchant_deep_link or '').strip()
    if _is_usable_web_url(merchant_link):
        if product.source == AffiliateProduct.SOURCE_AWIN:
            publisher_id = getattr(settings, 'AWIN_PUBLISHER_ID', '2612792')
            encoded_url = quote(merchant_link, safe='')
            return f'https://www.awin1.com/cread.php?awinaffid={publisher_id}&ued={encoded_url}'
        elif product.source == AffiliateProduct.SOURCE_RAKUTEN:
            rakuten_id = '7OwTtzNBeMo'
            encoded_url = quote(merchant_link, safe='')
            return f'https://click.linksynergy.com/link?id={rakuten_id}&type=15&murl={encoded_url}'
        return merchant_link

    return raw_link


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
    GET /api/affiliate/products/<id>/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductDetailSerializer
    queryset = AffiliateProduct.objects.filter(is_active=True).annotate(
        _favorites_count=Count('favorites', distinct=True),
        _clicks_count=Count('clicks', distinct=True),
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
    summary="Record Product Click & Generate Redirect URL",
    description="Records outbound affiliate link click for conversion analytics, and returns validated tracking URL.",
    responses={
        200: OpenApiResponse(description="Click recorded; returns affiliate tracking redirect URL"),
        404: OpenApiResponse(description="Product not found"),
    }
)
class ProductClickView(APIView):
    """
    POST /api/affiliate/products/<id>/click/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        try:
            product = AffiliateProduct.objects.get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user if request.user.is_authenticated else None
        ProductClick.objects.create(product=product, user=user)

        return Response({
            'success': True,
            'message': 'Click recorded. Redirect user to affiliate_url.',
            'data': {
                'affiliate_url': build_affiliate_url(product),
                'product_name':  product.name,
                'brand':         product.brand,
            }
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
    GET /api/affiliate/brands/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        qs = AffiliateProduct.objects.filter(is_active=True)

        source = request.query_params.get('source')
        if source in ('awin', 'rakuten'):
            qs = qs.filter(source=source)

        brands_raw = (
            qs
            .values('brand', 'source')
            .annotate(product_count=Count('id'))
            .order_by('brand')
        )

        merged = {}
        for row in brands_raw:
            key = (row['brand'].strip().lower(), row['source'])
            if key in merged:
                merged[key]['product_count'] += row['product_count']
            else:
                merged[key] = {
                    'brand':         row['brand'].strip().title(),
                    'source':        row['source'],
                    'product_count': row['product_count'],
                }

        brands = sorted(merged.values(), key=lambda x: x['brand'].lower())

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
    GET /api/affiliate/categories/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        categories = (
            AffiliateProduct.objects
            .filter(is_active=True)
            .exclude(category='')
            .values('category')
            .annotate(product_count=Count('id'))
            .order_by('category')
        )
        return Response({
            'success': True,
            'message': 'Categories retrieved successfully',
            'data': {
                'categories': list(categories)
            }
        }, status=status.HTTP_200_OK)
