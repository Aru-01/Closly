from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q, Count, Case, When, Value, IntegerField
from django.conf import settings
from urllib.parse import quote
from .models import AffiliateProduct, ProductClick, ProductFavorite
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
    authentication_classes = [JWTAuthentication]
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

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [p.id for p in page]
            fav_counts = dict(
                ProductFavorite.objects.filter(product_id__in=page_ids)
                .values('product_id')
                .annotate(c=Count('id'))
                .values_list('product_id', 'c')
            )
            for p in page:
                p._favorites_count = fav_counts.get(p.id, 0)

            user_fav_ids = set()
            if request.user and request.user.is_authenticated:
                user_fav_ids = set(
                    ProductFavorite.objects.filter(
                        user=request.user,
                        product_id__in=page_ids
                    ).values_list('product_id', flat=True)
                )

            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


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
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductDetailSerializer
    queryset = AffiliateProduct.objects.filter(is_active=True).annotate(_favorites_count=Count('favorites', distinct=True))

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
    authentication_classes = [JWTAuthentication]

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
    based on their UserPreference (style match, color palette, preferred brands, and categories)
    and gender ratio balancing:
    - If user gender is Male: 65% Male/Unisex products, 35% Female products.
    - If user gender is Female: 65% Female products, 35% Male/Unisex products.
    - If user gender is unspecified / other / unauthenticated: standard taste profile ranking.
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def _get_female_filter(self):
        female_cats = ['women', 'dress', 'skirt']
        female_cat_q = Q()
        for fc in female_cats:
            female_cat_q |= Q(category__icontains=fc)

        female_brands = ['Twinset', 'Tory Burch Eu', 'Needs No Label', 'Needs no label']
        female_brand_q = Q(brand__in=female_brands)

        female_words = [
            'dress', 'skirt', 'shirtdress', 'sundress', 'midaxi', 'midi dress', 'maxi dress', 'mini dress',
            'wrap dress', 'mini-jupe', 'robe', 'camisole', 'halterneck', 'jumpsuit', 'strappy heels', 'heels',
            'slingback', "d'orsay", 'pump', 'pumps', 'bra', 'brassière', 'bralette', 'bikini', 'blouse',
            'soutien-gorge', 'satchel', 'maternity', 'mary jane', 'fille', 'swimsuit'
        ]
        female_word_q = Q()
        for fw in female_words:
            female_word_q |= Q(name__icontains=fw)

        return female_cat_q | female_brand_q | female_word_q

    def _apply_relevance_scoring(self, qs, user):
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
            if b and b.strip():
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
            return qs.annotate(relevance_score=score_expression).order_by('-relevance_score', '-created_at')

        return qs.order_by('-created_at')

    def get_queryset(self):
        user = self.request.user
        qs = AffiliateProduct.objects.filter(is_active=True)
        return self._apply_relevance_scoring(qs, user)

    def paginate_queryset(self, queryset):
        user = self.request.user
        gender = getattr(user, 'gender', None) if user and user.is_authenticated else None
        if gender:
            gender = gender.lower()

        if gender not in ('male', 'female'):
            return super().paginate_queryset(queryset)

        female_filter = self._get_female_filter()
        base_qs = AffiliateProduct.objects.filter(is_active=True)

        scored_female = self._apply_relevance_scoring(base_qs.filter(female_filter), user)
        scored_male = self._apply_relevance_scoring(base_qs.exclude(female_filter), user)

        if gender == 'male':
            primary_qs = scored_male
            secondary_qs = scored_female
        else:
            primary_qs = scored_female
            secondary_qs = scored_male

        page_size = self.paginator.get_page_size(self.request) or getattr(self.paginator, 'page_size', 20) or 20
        page_number_str = self.request.query_params.get(self.paginator.page_query_param, 1)
        try:
            page_number = int(page_number_str)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1

        primary_target = int(round(page_size * 0.65))
        secondary_target = page_size - primary_target

        p_start = (page_number - 1) * primary_target
        p_end = p_start + primary_target
        s_start = (page_number - 1) * secondary_target
        s_end = s_start + secondary_target

        primary_batch = list(primary_qs[p_start:p_end])
        secondary_batch = list(secondary_qs[s_start:s_end])

        # Backfill if one pool is exhausted near the end of catalog
        if len(primary_batch) < primary_target:
            needed = primary_target - len(primary_batch)
            extra_sec = list(secondary_qs[s_end:s_end + needed])
            secondary_batch.extend(extra_sec)
        elif len(secondary_batch) < secondary_target:
            needed = secondary_target - len(secondary_batch)
            extra_prim = list(primary_qs[p_end:p_end + needed])
            primary_batch.extend(extra_prim)

        # Smooth 2:1 Interleaving: (P, P, S, P, P, S...)
        interleaved = []
        p_i, s_i = 0, 0
        while p_i < len(primary_batch) or s_i < len(secondary_batch):
            for _ in range(2):
                if p_i < len(primary_batch):
                    interleaved.append(primary_batch[p_i])
                    p_i += 1
            if s_i < len(secondary_batch):
                interleaved.append(secondary_batch[s_i])
                s_i += 1

        total_count = primary_qs.count() + secondary_qs.count()
        from django.core.paginator import Paginator, Page
        paginator = Paginator(range(total_count), page_size)
        try:
            self.paginator.page = paginator.page(page_number)
        except Exception:
            self.paginator.page = Page([], page_number, paginator)

        self.paginator.request = self.request
        return interleaved

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [p.id for p in page]
            fav_counts = dict(
                ProductFavorite.objects.filter(product_id__in=page_ids)
                .values('product_id')
                .annotate(c=Count('id'))
                .values_list('product_id', 'c')
            )
            for p in page:
                p._favorites_count = fav_counts.get(p.id, 0)

            user_fav_ids = set()
            if request.user and request.user.is_authenticated:
                user_fav_ids = set(
                    ProductFavorite.objects.filter(
                        user=request.user,
                        product_id__in=page_ids
                    ).values_list('product_id', flat=True)
                )

            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            response = self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            response = Response(serializer.data)

        user = request.user
        prefs_summary = None
        gender_summary = getattr(user, 'gender', None) if user and user.is_authenticated else None
        if user and user.is_authenticated and hasattr(user, 'preferences'):
            prefs = user.preferences
            prefs_summary = {
                'palette': prefs.color_palette or 'neutral_minimalist',
                'styles': prefs.style_match or ['minimalist'],
                'preferred_brands': prefs.preferred_brands or []
            }
        
        response.data['user_taste_profile'] = prefs_summary
        if gender_summary in ('male', 'female'):
            response.data['gender_balance'] = {
                'user_gender': gender_summary,
                'primary_ratio': '65%',
                'secondary_ratio': '35%',
            }
        response.data['message'] = "Personalized 'For You' products curated based on your Style DNA and balanced preferences."
        return response


# ------------------------------------------------------------------ #
# Product Love / Save / Wishlist System
# ------------------------------------------------------------------ #

class ProductFavoriteToggleView(APIView):
    """
    POST /api/affiliate/products/<id>/love/
    POST /api/affiliate/products/<id>/favorite/
    POST /api/affiliate/products/<id>/save/

    Toggles favorite / love status on a product for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        try:
            product = AffiliateProduct.objects.only('id').get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Product not found or inactive',
                'data': None
            }, status=status.HTTP_404_NOT_FOUND)

        deleted_count, _ = ProductFavorite.objects.filter(product_id=pk, user=request.user).delete()
        if deleted_count > 0:
            is_loved = False
            status_str = 'unloved'
            message = 'Product removed from your saved wishlist'
        else:
            ProductFavorite.objects.create(product_id=pk, user=request.user)
            is_loved = True
            status_str = 'loved'
            message = 'Product saved to your wishlist!'

        favorites_count = ProductFavorite.objects.filter(product_id=pk).count()

        return Response({
            'success': True,
            'message': message,
            'data': {
                'status': status_str,
                'is_loved': is_loved,
                'favorites_count': favorites_count,
                'product_id': pk,
            }
        }, status=status.HTTP_200_OK)


class SavedProductsListView(generics.ListAPIView):
    """
    GET /api/affiliate/products/saved/
    GET /api/affiliate/products/favorites/

    Returns all products loved / saved by the authenticated user with O(1) query complexity.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        return (
            AffiliateProduct.objects.filter(
                favorites__user=self.request.user,
                is_active=True
            )
            .order_by('-favorites__created_at')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [p.id for p in page]
            fav_counts = dict(
                ProductFavorite.objects.filter(product_id__in=page_ids)
                .values('product_id')
                .annotate(c=Count('id'))
                .values_list('product_id', 'c')
            )
            for p in page:
                p._favorites_count = fav_counts.get(p.id, 0)

            # In this view, all items on the page are favorited by request.user
            user_fav_ids = set(page_ids)

            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


