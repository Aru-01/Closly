import hashlib
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductClick, Brand
from affiliate.serializers import AffiliateProductDetailSerializer
from affiliate.throttles import ProductClickRateThrottle

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


def _get_ip_prefix(request) -> str:
    """Extract anonymized network prefix (/24 for IPv4, /48 for IPv6) without storing raw PII."""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if ip:
        ip = ip.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    if not ip:
        return ''
    if '.' in ip:
        octets = ip.split('.')
        if len(octets) == 4:
            return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
    elif ':' in ip:
        segments = ip.split(':')
        if len(segments) >= 3:
            return f"{':'.join(segments[:3])}::/48"
    return ''


def _get_ua_hash(request) -> str:
    """Compute SHA-256 hash of the client User-Agent."""
    ua = request.META.get('HTTP_USER_AGENT', '')
    return hashlib.sha256(ua.encode('utf-8')).hexdigest() if ua else ''


def build_affiliate_url(product, click=None, click_ref=None, surface='for_you') -> str:
    """
    Build the outbound affiliate tracking URL with full attribution metadata.

    Attribution specs:
    - AWIN:
      Appends `clickref=<click_ref.hex>` and `clickref2=<surface>`.
      Correctly preserves and merges existing query parameters on pclick.php and cread.php links.
    - Rakuten Advertising:
      Appends `u1=<click_ref.hex>` SubID token.
    - Shopify / Direct merchants:
      Appends standard UTM tracking params + `utm_content=<click_ref.hex>`.
    """
    raw_link = (product.aw_deep_link or '').strip()
    if not raw_link.startswith(('http://', 'https://')):
        merchant_link = (product.merchant_deep_link or '').strip()
        if _is_usable_web_url(merchant_link):
            if product.source == AffiliateProduct.SOURCE_AWIN:
                publisher_id = getattr(settings, 'AWIN_PUBLISHER_ID', '2612792')
                encoded_url = quote(merchant_link, safe='')
                raw_link = f'https://www.awin1.com/cread.php?awinaffid={publisher_id}&ued={encoded_url}'
            elif product.source == AffiliateProduct.SOURCE_RAKUTEN:
                rakuten_id = '7OwTtzNBeMo'
                encoded_url = quote(merchant_link, safe='')
                raw_link = f'https://click.linksynergy.com/link?id={rakuten_id}&type=15&murl={encoded_url}'
            else:
                raw_link = merchant_link
        else:
            return raw_link

    c_ref = None
    surf = surface or 'feed'

    if click and getattr(click, 'click_ref', None):
        c_ref = click.click_ref
        surf = getattr(click, 'surface', surf) or surf
    elif click_ref:
        c_ref = click_ref

    if not c_ref:
        return raw_link

    click_ref_hex = c_ref.hex if hasattr(c_ref, 'hex') else str(c_ref).replace('-', '')
    surface = str(surf)

    try:
        parts = urlsplit(raw_link)
        query_params = dict(parse_qsl(parts.query, keep_blank_values=True))

        if product.source == AffiliateProduct.SOURCE_AWIN or 'awin1.com' in parts.netloc:
            query_params['clickref'] = click_ref_hex
            if surface:
                query_params['clickref2'] = surface
        elif product.source == AffiliateProduct.SOURCE_RAKUTEN or 'linksynergy.com' in parts.netloc:
            query_params['u1'] = click_ref_hex
        else:
            query_params['utm_source'] = 'closly'
            query_params['utm_medium'] = 'app'
            query_params['utm_campaign'] = 'feed'
            query_params['utm_content'] = click_ref_hex
            if surface:
                query_params['utm_term'] = surface

        new_query = urlencode(query_params)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error appending attribution to link: {e}")
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
    summary="Record Product Click & Generate Attributed Redirect URL",
    description=(
        "Records outbound affiliate link click with unique click reference UUID (AWIN clickref / Rakuten u1 / UTM), "
        "enforces 30 clicks/hour rate limit, supports Idempotency-Key, and returns attribution details."
    ),
    responses={
        200: OpenApiResponse(description="Click recorded; returns click reference token and outbound tracking redirect URL"),
        404: OpenApiResponse(description="Product not found or inactive"),
        429: OpenApiResponse(description="Click rate limit exceeded"),
    }
)
class ProductClickView(APIView):
    """
    POST /api/affiliate/products/<id>/click/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [ProductClickRateThrottle]

    def post(self, request, pk):
        try:
            product = AffiliateProduct.objects.get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found or inactive'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user if request.user and request.user.is_authenticated else None

        surface = (
            request.data.get('surface')
            or request.query_params.get('surface')
            or 'feed'
        )
        session_id = (
            request.headers.get('X-Session-ID')
            or request.data.get('session_id')
            or request.query_params.get('session_id')
            or ''
        )
        idempotency_key = (
            request.headers.get('Idempotency-Key')
            or request.headers.get('X-Idempotency-Key')
            or request.data.get('idempotency_key')
            or ''
        )

        # Idempotency check: if key provided, return previously minted click
        if idempotency_key:
            existing = ProductClick.objects.filter(
                idempotency_key=idempotency_key,
                user=user,
                product=product,
            ).first()
            if existing:
                outbound_url = build_affiliate_url(product, click=existing)
                return Response({
                    'success': True,
                    'message': 'Click retrieved (idempotent). Redirect user to affiliate_url.',
                    'data': {
                        'click_id': str(existing.click_ref),
                        'click_ref': str(existing.click_ref),
                        'url': outbound_url,
                        'affiliate_url': outbound_url,
                        'product_name': product.name,
                        'brand': product.brand,
                    }
                }, status=status.HTTP_200_OK)

        ip_prefix = _get_ip_prefix(request)
        ua_hash = _get_ua_hash(request)

        with transaction.atomic():
            click = ProductClick.objects.create(
                product=product,
                user=user,
                surface=surface[:50],
                session_id=session_id[:100],
                user_agent_hash=ua_hash[:64],
                ip_prefix=ip_prefix[:45],
                idempotency_key=idempotency_key[:100],
            )

        outbound_url = build_affiliate_url(product, click=click)

        return Response({
            'success': True,
            'message': 'Click recorded. Redirect user to affiliate_url.',
            'data': {
                'click_id': str(click.click_ref),
                'click_ref': str(click.click_ref),
                'url': outbound_url,
                'affiliate_url': outbound_url,
                'product_name': product.name,
                'brand': product.brand,
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
        if source in ('awin', 'rakuten', 'shopify', 'myc_feed'):
            qs = qs.filter(source=source)

        brands_raw = (
            qs
            .order_by('brand')
            .values('brand', 'source')
            .annotate(product_count=Count('id'))
        )

        merged = {}
        for row in brands_raw:
            key = (row['brand'].strip().lower(), row['source'])
            if key in merged:
                merged[key]['product_count'] += row['product_count']
            else:
                merged[key] = {
                    'brand':         row['brand'].strip(),
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
            .order_by('category')
            .values('category')
            .annotate(product_count=Count('id'))
        )
        return Response({
            'success': True,
            'message': 'Categories retrieved successfully',
            'data': {
                'categories': list(categories)
            }
        }, status=status.HTTP_200_OK)
