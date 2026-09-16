from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q, Count, Case, When, Value, IntegerField
from django.conf import settings
from urllib.parse import quote
from .models import AffiliateProduct, ProductClick
from .serializers import AffiliateProductListSerializer, AffiliateProductDetailSerializer



# Domains that are mobile app deep links / app-store redirects — not real web pages.
# These cannot be used as a `ued=` destination in Awin's cread.php.
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
    # Must start with http(s)
    if not url_lower.startswith(('http://', 'https://')):
        return False
    # Reject known app-link domains
    for domain in _APP_LINK_DOMAINS:
        if domain in url_lower:
            return False
    return True


def build_affiliate_url(product):
    """
    Build the correct affiliate tracking URL for a product.

    Awin products
    -------------
    If merchant_deep_link is a real web URL (not a mobile app link), we wrap it
    in Awin's cread.php with `ued=<encoded_product_url>`. This gives both
    click tracking AND a direct landing on the specific product page.

    If merchant_deep_link is an app deep link (e.g. onelink.me) or missing,
    we fall back to the raw aw_deep_link so the user at least reaches the
    brand's website.

    Rakuten products
    ----------------
    aw_deep_link already contains the correct tracked deep link — return as-is.
    """
    if product.source == AffiliateProduct.SOURCE_AWIN:
        merchant_url = product.merchant_deep_link or ''

        if _is_usable_web_url(merchant_url):
            publisher_id = getattr(settings, 'AWIN_PUBLISHER_ID', '2612792')
            # Extract merchant ID (m=XXXXX) from the stored aw_deep_link
            mid = ''
            raw = product.aw_deep_link or ''
            if 'm=' in raw:
                try:
                    mid = raw.split('m=')[1].split('&')[0]
                except IndexError:
                    mid = ''
            encoded_url = quote(merchant_url, safe='')
            if mid:
                return (
                    f'https://www.awin1.com/cread.php'
                    f'?awinaffid={publisher_id}&m={mid}&ued={encoded_url}'
                )
            return (
                f'https://www.awin1.com/cread.php'
                f'?awinaffid={publisher_id}&ued={encoded_url}'
            )

        # merchant_deep_link is an app link or missing — use pclick fallback
        return product.aw_deep_link

    # Rakuten: already a correct tracked deep link
    return product.aw_deep_link


# ------------------------------------------------------------------ #
# Pagination
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
# Newsfeed — main product list
# ------------------------------------------------------------------ #

class AffiliateProductNewsfeedView(generics.ListAPIView):
    """
    GET /api/affiliate/products/

    Returns paginated affiliate products for the home newsfeed.

    Query params:
        search      — full-text search across name, brand, description
        brand       — exact brand filter (case-insensitive)
        category    — partial category match
        colour      — colour filter
        min_price   — minimum price
        max_price   — maximum price
        ordering    — price_asc | price_desc | newest | discount
        page        — page number
        page_size   — results per page (default 20, max 100)
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        qs = AffiliateProduct.objects.filter(is_active=True)

        search    = self.request.query_params.get('search')
        brand     = self.request.query_params.get('brand')
        category  = self.request.query_params.get('category')
        colour    = self.request.query_params.get('colour')
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        ordering  = self.request.query_params.get('ordering')
        source    = self.request.query_params.get('source')  # 'awin' | 'rakuten'

        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(brand__icontains=search) |
                Q(description__icontains=search)
            )

        if brand:
            qs = qs.filter(brand__iexact=brand)

        if category:
            qs = qs.filter(category__icontains=category)

        if colour:
            qs = qs.filter(colour__icontains=colour)

        if source in ('awin', 'rakuten'):
            qs = qs.filter(source=source)

        if min_price:
            try:
                qs = qs.filter(price__gte=float(min_price))
            except ValueError:
                pass

        if max_price:
            try:
                qs = qs.filter(price__lte=float(max_price))
            except ValueError:
                pass

        order_map = {
            'price_asc':  'price',
            'price_desc': '-price',
            'newest':     '-created_at',
            'discount':   'price',   # cheapest first as proxy for best deal
        }
        qs = qs.order_by(order_map.get(ordering, '-created_at'))

        return qs


# ------------------------------------------------------------------ #
# Product detail
# ------------------------------------------------------------------ #

class AffiliateProductDetailView(generics.RetrieveAPIView):
    """
    GET /api/affiliate/products/<id>/

    Returns full product details including the affiliate tracking link.
    The mobile app should open aw_deep_link in an in-app browser when
    the user taps 'Buy'.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = AffiliateProductDetailSerializer
    queryset = AffiliateProduct.objects.filter(is_active=True)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Product retrieved successfully',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)


# ------------------------------------------------------------------ #
# Click tracking  (called before opening the affiliate link)
# ------------------------------------------------------------------ #

class ProductClickView(APIView):
    """
    POST /api/affiliate/products/<id>/click/

    Records a click for internal analytics, then returns the Awin
    affiliate tracking URL for the mobile app to open.

    The app flow is:
        1. User taps 'Buy'
        2. App calls POST /api/affiliate/products/<id>/click/
        3. Backend records the click and returns { affiliate_url }
        4. App opens affiliate_url in WebView / system browser
        5. User completes purchase on brand website
        6. Awin records conversion → MyClosly earns commission

    Authentication is optional — works for both logged-in and guest users.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, pk):
        try:
            product = AffiliateProduct.objects.get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Record click — user may or may not be authenticated
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


# ------------------------------------------------------------------ #
# Brands list
# ------------------------------------------------------------------ #

class AffiliateBrandsListView(APIView):
    """
    GET /api/affiliate/brands/

    Returns all unique brands with product counts.
    Use this to populate the brand filter on the app.

    Query params:
        source — 'awin' | 'rakuten' | omit for both networks combined
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

        # Merge brands that differ only in capitalisation
        # e.g. "Needs No Label" and "Needs no label" → "Needs No Label"
        merged = {}
        for row in brands_raw:
            key = (row['brand'].strip().lower(), row['source'])
            if key in merged:
                merged[key]['product_count'] += row['product_count']
            else:
                # Use title-cased version as the canonical name
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


# ------------------------------------------------------------------ #
# Categories list
# ------------------------------------------------------------------ #

class AffiliateCategoriesListView(APIView):
    """
    GET /api/affiliate/categories/

    Returns all unique categories with product counts.
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


class AffiliateProductForYouView(generics.ListAPIView):
    """
    GET /api/affiliate/products/for-you/

    Returns personalized affiliate products recommended specifically for the current user
    based on their UserPreference (style match, color palette, preferred brands, and categories).
    If the user is not authenticated or has no preferences, returns curated popular products.
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        qs = AffiliateProduct.objects.filter(is_active=True)
        user = self.request.user

        if not user or not user.is_authenticated or not hasattr(user, 'preferences'):
            return qs.order_by('-created_at')

        prefs = user.preferences
        preferred_brands = prefs.preferred_brands or []
        palette = prefs.color_palette or ''
        styles = prefs.style_match or []
        clothing_cats = prefs.clothing_categories or {}

        # Color keywords mapping from user palette
        palette_color_map = {
            'neutral_minimalist': ['black', 'white', 'grey', 'gray', 'beige', 'navy', 'cream', 'charcoal', 'off-white'],
            'bold_rich': ['red', 'blue', 'green', 'yellow', 'purple', 'burgundy', 'orange', 'emerald', 'crimson'],
            'soft_romantic': ['pink', 'pastel', 'lavender', 'rose', 'peach', 'mint', 'cream', 'blush'],
            'earthy_warm': ['brown', 'tan', 'olive', 'khaki', 'terracotta', 'rust', 'camel', 'espresso'],
        }
        color_keywords = palette_color_map.get(palette, [])

        # Build Q filters with relevance scoring
        brand_q = Q()
        for b in preferred_brands:
            if b:
                brand_q |= Q(brand__icontains=b.strip())

        color_q = Q()
        for c in color_keywords:
            color_q |= Q(colour__icontains=c) | Q(name__icontains=c)

        style_q = Q()
        for s in styles:
            style_q |= Q(name__icontains=s) | Q(description__icontains=s)

        category_keywords = []
        if isinstance(clothing_cats, dict):
            for cat_list in clothing_cats.values():
                if isinstance(cat_list, list):
                    category_keywords.extend(cat_list)
        cat_q = Q()
        for ck in category_keywords[:10]:
            cat_q |= Q(category__icontains=ck) | Q(name__icontains=ck)

        cases = []
        if bool(brand_q):
            cases.append(When(brand_q, then=Value(35)))
        if bool(color_q):
            cases.append(When(color_q, then=Value(25)))
        if bool(cat_q):
            cases.append(When(cat_q, then=Value(20)))
        if bool(style_q):
            cases.append(When(style_q, then=Value(20)))

        if cases:
            score_expression = Case(*cases, default=Value(0), output_field=IntegerField())
            return qs.annotate(relevance_score=score_expression).order_by('-relevance_score', '?')

        return qs.order_by('-created_at', '?')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        user = request.user
        prefs_summary = None
        if user and user.is_authenticated and hasattr(user, 'preferences'):
            prefs = user.preferences
            prefs_summary = {
                'palette': prefs.color_palette or 'neutral_minimalist',
                'styles': prefs.style_match or ['minimalist'],
                'preferred_brands': prefs.preferred_brands or []
            }
        
        response.data['user_taste_profile'] = prefs_summary
        response.data['message'] = "Personalized 'For You' products curated based on your Style DNA."
        return response

