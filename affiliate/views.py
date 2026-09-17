import re
import random
import operator
from functools import reduce
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

    Both Awin and Rakuten networks provide pre-generated, fully tracked deep links
    in `aw_deep_link` (e.g. Awin's `pclick.php?p=...&a=...&m=...` and Rakuten's
    `click.linksynergy.com/link?...`).
    Using this official tracking link directly guarantees instantaneous redirection
    to the brand's exact product page without blank/white pages, while reliably
    recording publisher attribution and conversions.
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


class ForYouPagination(NewsfeedPagination):
    """
    Pagination class for the 'For You' personalized discovery feed.
    Carries the discovery seed in pagination links (seed=<int>) so infinite scrolling
    remains completely non-repetitive across pages, while fresh requests without seed
    (or with refresh=true) produce freshly randomized product recommendations.
    """
    def __init__(self):
        super().__init__()
        self.seed = None

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        if self.seed is not None and isinstance(response.data, dict) and 'data' in response.data:
            response.data['data']['seed'] = self.seed
        return response

    def get_next_link(self):
        link = super().get_next_link()
        if link and self.seed is not None:
            from rest_framework.utils.urls import replace_query_param
            link = replace_query_param(link, 'seed', self.seed)
        return link

    def get_previous_link(self):
        link = super().get_previous_link()
        if link and self.seed is not None:
            from rest_framework.utils.urls import replace_query_param
            link = replace_query_param(link, 'seed', self.seed)
        return link


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
        qs = AffiliateProduct.objects.filter(is_active=True, price__gt=0).exclude(
            Q(aw_deep_link__contains='awinmid=99999') |
            Q(aw_product_id__startswith='closly_') |
            Q(aw_product_id__startswith='mock_')
        )

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
            except ValueError as e:
                import logging
                logging.getLogger(__name__).warning(f"Invalid min_price parameter: {min_price} - {e}")

        if max_price:
            try:
                qs = qs.filter(price__lte=float(max_price))
            except ValueError as e:
                import logging
                logging.getLogger(__name__).warning(f"Invalid max_price parameter: {max_price} - {e}")

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

    Returns personalized, diverse affiliate products recommended specifically for the current user:
    1. Variant De-duplication: Drops consecutive identical product models and repeated image variants
       (e.g. Uniqlo Puffer in Olive, Navy, Black are collapsed to the best-matching single variant).
    2. Additive Multi-Signal Taste Scoring: Combines user preferences (preferred brands, color palette,
       clothing categories, style match) and engagement affinity (loved/favorited brands and closet items).
    3. Brand & Category Diversity Reranking: Prevents feed fatigue by interleaving different brands and categories.
    4. Gender Ratio Balancing:
       - Male users: 65% Male/Unisex products, 35% Female products.
       - Female users: 65% Female products, 35% Male/Unisex products.
       - Other / Unauthenticated: Balanced diverse feed.
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = ForYouPagination

    @staticmethod
    def _base_model_name(name: str) -> str:
        """
        Extract the canonical base model name by stripping color/size variants.
        e.g. 'Uniqlo Ultra Light Down Seamless Puffer (Olive)' -> 'uniqlo ultra light down seamless puffer'
             'Puma Suede Classic - Black' -> 'puma suede classic'
        """
        s = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
        s = re.sub(r'\s*-\s*(?:black|white|grey|gray|navy|olive|blue|red|green|brown|beige|tan|pink|orange|khaki|cream|burgundy|yellow)\b.*$', '', s, flags=re.IGNORECASE).strip()
        return s.lower()

    def _get_clean_base_queryset(self):
        """
        Returns only genuine, high-quality, verified affiliate products.
        Excludes legacy non-routable mock products and invalid prices.
        """
        return AffiliateProduct.objects.filter(
            is_active=True,
            price__gt=0
        ).exclude(
            Q(aw_deep_link__contains='awinmid=99999') |
            Q(aw_product_id__startswith='closly_') |
            Q(aw_product_id__startswith='mock_')
        )

    def _get_female_filter(self):
        female_cats = ['women', 'dress', 'skirt', 'bra', 'lingerie', 'maternity', 'womenswear']
        female_cat_q = Q()
        for fc in female_cats:
            female_cat_q |= Q(category__icontains=fc)

        female_words = [
            'dress', 'skirt', 'shirtdress', 'sundress', 'midaxi', 'midi dress', 'maxi dress', 'mini dress',
            'wrap dress', 'mini-jupe', 'robe', 'camisole', 'halterneck', 'jumpsuit', 'strappy heels', 'heels',
            'slingback', "d'orsay", 'pump', 'pumps', 'bra', 'brassière', 'bralette', 'bikini', 'blouse',
            'soutien-gorge', 'satchel', 'maternity', 'mary jane', 'fille', 'swimsuit', 'ballet', 'sandal',
            'espadrille', 'mule', 'wedge', 'earring', 'necklace', 'bracelet'
        ]
        female_word_q = Q()
        for fw in female_words:
            female_word_q |= Q(name__icontains=fw)

        # Unisex accessory keywords allow unisex items from fashion houses to belong to the male/unisex pool
        unisex_words = [
            'watch', 'cap', 'sunglasses', 'card case', 'cardholder', 'wallet', 'porte-cartes',
            'sneaker', 'trainer', 'basket', 'scarf', 'écharpe', 'foulard', 'belt', 'ceinture',
            'keyring', 'backpack', 'sac à dos', 'duffle', 'comb', 'blanket', 'socks',
            'recovery', 'brace', 'sleeve'
        ]
        unisex_q = Q()
        for uw in unisex_words:
            unisex_q |= Q(name__icontains=uw)

        # Needs No Label is strictly female fashion; Twinset & Tory Burch items are female unless pure unisex accessories
        female_brand_q = (
            Q(brand__iexact='Needs No Label') |
            (Q(brand__in=['Twinset', 'Tory Burch Eu', 'Needs no label']) & ~unisex_q)
        )

        return female_cat_q | female_brand_q | female_word_q

    def _get_user_affinity_brands(self, user):
        if not user or not user.is_authenticated:
            return set()

        if hasattr(self, '_cached_affinity_brands'):
            return self._cached_affinity_brands

        fav_brands = []
        try:
            fav_brands = list(ProductFavorite.objects.filter(user=user).values_list('product__brand', flat=True)[:30])
        except Exception:
            fav_brands = []

        closet_brands = []
        try:
            from closet.models import ClosetItem
            closet_brands = list(ClosetItem.objects.filter(user=user).exclude(brand='').values_list('brand', flat=True)[:30])
        except Exception:
            closet_brands = []

        self._cached_affinity_brands = set(b.strip().lower() for b in fav_brands + closet_brands if b and b.strip())
        return self._cached_affinity_brands

    def _apply_relevance_scoring(self, qs, user):
        if not user or not user.is_authenticated:
            return qs.order_by('-id')

        score_parts = []

        # 1. User engagement affinity (favorited brands, closet items) — cached per request to prevent duplicate queries
        affinity_brands = self._get_user_affinity_brands(user)
        if affinity_brands:
            aff_q = Q()
            for ab in list(affinity_brands)[:15]:
                aff_q |= Q(brand__iexact=ab)
            score_parts.append(Case(When(aff_q, then=Value(25)), default=Value(0), output_field=IntegerField()))

        # 2. User onboarding preferences
        if hasattr(user, 'preferences'):
            prefs = user.preferences
            preferred_brands = prefs.preferred_brands or []
            palette = prefs.color_palette or ''
            styles = prefs.style_match or []
            clothing_cats = prefs.clothing_categories or {}

            # Preferred Brands (+40)
            if preferred_brands:
                brand_q = Q()
                for b in preferred_brands:
                    if b and b.strip():
                        brand_q |= Q(brand__icontains=b.strip())
                score_parts.append(Case(When(brand_q, then=Value(40)), default=Value(0), output_field=IntegerField()))

            # Color Palette (+25)
            palette_color_map = {
                'neutral_minimalist': ['black', 'white', 'grey', 'gray', 'beige', 'navy', 'cream', 'charcoal', 'off-white'],
                'bold_rich': ['red', 'blue', 'green', 'yellow', 'purple', 'burgundy', 'orange', 'emerald', 'crimson'],
                'soft_romantic': ['pink', 'pastel', 'lavender', 'rose', 'peach', 'mint', 'cream', 'blush'],
                'earthy_warm': ['brown', 'tan', 'olive', 'khaki', 'terracotta', 'rust', 'camel', 'espresso'],
            }
            color_keywords = palette_color_map.get(palette, [])
            if color_keywords:
                color_q = Q()
                for c in color_keywords:
                    color_q |= Q(colour__icontains=c) | Q(name__icontains=c)
                score_parts.append(Case(When(color_q, then=Value(25)), default=Value(0), output_field=IntegerField()))

            # Clothing Categories (+20)
            category_keywords = []
            if isinstance(clothing_cats, dict):
                for cat_list in clothing_cats.values():
                    if isinstance(cat_list, list):
                        category_keywords.extend(cat_list)
            if category_keywords:
                cat_q = Q()
                for ck in category_keywords[:12]:
                    cat_q |= Q(category__icontains=ck) | Q(name__icontains=ck)
                score_parts.append(Case(When(cat_q, then=Value(20)), default=Value(0), output_field=IntegerField()))

            # Style Match (+15)
            if styles:
                style_q = Q()
                for s in styles:
                    style_q |= Q(name__icontains=s) | Q(description__icontains=s)
                score_parts.append(Case(When(style_q, then=Value(15)), default=Value(0), output_field=IntegerField()))

        if score_parts:
            composite_score = reduce(operator.add, score_parts)
            return qs.annotate(relevance_score=composite_score).order_by('-relevance_score', '-id')

        return qs.order_by('-id')

    @classmethod
    def _extract_unique_diverse_pool(cls, qs, target_count, skip_count=0, seed=None, max_watches=None):
        """
        Extracts `target_count` unique, non-repetitive products after skipping `skip_count`.
        1. Fairly samples candidates across all active brands in `qs` to avoid ID-based single-brand clustering.
        2. Deduplicates multiple color/size variants of the exact same product model and identical images.
        3. Applies seeded shuffling within relevance tiers so pull-to-refresh / new sessions
           generate fresh discoveries, while pagination (page=2, 3...) remains deterministic and non-repeating.
        4. When max_watches is specified, throttles watches per page to prevent watch flooding.
        """
        needed_total = skip_count + target_count
        candidate_limit = max(needed_total * 4, 180)

        # Multi-brand candidate sampling across brands in qs
        brands_in_qs = list(qs.order_by().values_list('brand', flat=True).distinct()[:8])
        if len(brands_in_qs) > 1:
            per_brand_limit = max(candidate_limit // len(brands_in_qs), 35)
            candidates = []
            for b in brands_in_qs:
                candidates.extend(list(qs.filter(brand=b)[:per_brand_limit]))
        else:
            candidates = list(qs[:candidate_limit])

        # Step 1: Variant de-duplication
        seen_models = set()
        seen_images = set()
        deduped = []

        for p in candidates:
            brand_clean = (p.brand or '').strip().lower()
            model_key = (brand_clean, cls._base_model_name(p.name))
            img_key = (brand_clean, p.image_url.strip()) if p.image_url else None

            if model_key in seen_models:
                continue
            if img_key and img_key in seen_images:
                continue

            seen_models.add(model_key)
            if img_key:
                seen_images.add(img_key)

            deduped.append(p)

        # Step 2: Seeded tiered shuffling if seed is provided
        if seed is not None and deduped:
            tiers = {}
            for p in deduped:
                score = getattr(p, 'relevance_score', 0) or 0
                tiers.setdefault(score, []).append(p)

            shuffled = []
            for score in sorted(tiers.keys(), reverse=True):
                tier_items = list(tiers[score])
                tier_seed = (int(seed) + int(score) * 7919) % 2147483647
                rng = random.Random(tier_seed)
                rng.shuffle(tier_items)
                shuffled.extend(tier_items)
            deduped = shuffled

        # Step 3: Page slice with optional watch capping
        def is_watch_item(p):
            b = (p.brand or '').lower()
            n = (p.name or '').lower()
            return 'd1 milano' in b or 'watch' in n or 'montre' in n or 'reloj' in n

        if max_watches is not None:
            page_items = []
            skipped = 0
            watches_in_page = 0

            for p in deduped:
                item_is_watch = is_watch_item(p)
                if skipped < skip_count:
                    skipped += 1
                    continue

                if item_is_watch:
                    if watches_in_page < max_watches:
                        page_items.append(p)
                        watches_in_page += 1
                else:
                    page_items.append(p)

                if len(page_items) >= target_count:
                    break

            return page_items

        return deduped[skip_count:skip_count + target_count]

    @staticmethod
    def _is_watch(p):
        b = (p.brand or '').lower()
        n = (p.name or '').lower()
        return 'd1 milano' in b or 'watch' in n or 'montre' in n or 'reloj' in n

    @classmethod
    def _interleave_diverse(cls, primary_batch, secondary_batch):
        """
        Interleaves primary and secondary items with:
        1. Strict watch spacing (no consecutive watches, separated by at least 2 non-watches).
        2. Brand diversity (no consecutive identical brands when alternatives exist).
        3. Smooth distribution across the page.
        """
        combined = []
        p_list = list(primary_batch)
        s_list = list(secondary_batch)
        items_since_watch = 99

        while p_list or s_list:
            last_item = combined[-1] if combined else None
            last_brand = (last_item.brand or '').strip().lower() if last_item else None
            last_was_watch = cls._is_watch(last_item) if last_item else False

            sources = []
            if len(p_list) >= len(s_list):
                sources = [(p_list, 'p'), (s_list, 's')]
            else:
                sources = [(s_list, 's'), (p_list, 'p')]

            chosen_source = None
            chosen_idx = 0
            found = False

            # Try to pick candidate with different brand and no consecutive watches
            for src, _ in sources:
                if not src:
                    continue
                for idx, cand in enumerate(src):
                    cand_brand = (cand.brand or '').strip().lower()
                    cand_is_watch = cls._is_watch(cand)

                    if cand_brand != last_brand and not (last_was_watch and cand_is_watch):
                        if cand_is_watch and items_since_watch < 3 and len(src) > 1:
                            continue
                        chosen_source = src
                        chosen_idx = idx
                        found = True
                        break
                if found:
                    break

            if not found:
                for src, _ in sources:
                    if not src:
                        continue
                    for idx, cand in enumerate(src):
                        cand_is_watch = cls._is_watch(cand)
                        if not (last_was_watch and cand_is_watch):
                            chosen_source = src
                            chosen_idx = idx
                            found = True
                            break
                    if found:
                        break

            if not found:
                chosen_source = p_list if p_list else s_list
                chosen_idx = 0

            picked = chosen_source.pop(chosen_idx)
            combined.append(picked)
            if cls._is_watch(picked):
                items_since_watch = 0
            else:
                items_since_watch += 1

        return combined

    @staticmethod
    def _diversify_brands(items):
        if len(items) <= 2:
            return items

        diversified = []
        remaining = list(items)

        while remaining:
            last_brand = diversified[-1].brand.strip().lower() if diversified else None
            chosen_idx = 0
            if last_brand is not None:
                for idx, candidate in enumerate(remaining):
                    if candidate.brand.strip().lower() != last_brand:
                        chosen_idx = idx
                        break
            diversified.append(remaining.pop(chosen_idx))

        return diversified

    def get_queryset(self):
        user = self.request.user
        qs = self._get_clean_base_queryset()
        return self._apply_relevance_scoring(qs, user)

    def paginate_queryset(self, queryset):
        user = self.request.user
        gender = getattr(user, 'gender', None) if user and user.is_authenticated else None
        if gender:
            gender = gender.lower()

        page_size = self.paginator.get_page_size(self.request) or getattr(self.paginator, 'page_size', 20) or 20
        page_number_str = self.request.query_params.get(self.paginator.page_query_param, 1)
        try:
            page_number = int(page_number_str)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1

        # Determine discovery seed for dynamic refresh
        seed_param = self.request.query_params.get('seed')
        refresh_param = self.request.query_params.get('refresh', '').lower() in ('true', '1', 'yes')

        if refresh_param or not seed_param or (page_number == 1 and not seed_param):
            seed = random.randint(100000, 999999)
        else:
            try:
                seed = int(seed_param)
            except (ValueError, TypeError):
                seed = abs(hash(str(seed_param))) % 1000000

        if hasattr(self.paginator, 'seed'):
            self.paginator.seed = seed

        base_qs = self._get_clean_base_queryset()

        if gender not in ('male', 'female'):
            skip_count = (page_number - 1) * page_size
            scored_qs = self._apply_relevance_scoring(base_qs, user)
            batch = self._extract_unique_diverse_pool(scored_qs, page_size, skip_count, seed=seed, max_watches=2)
            diversified = self._diversify_brands(batch)

            from django.core.paginator import Paginator, Page
            total_count = scored_qs.count()
            paginator = Paginator(range(total_count), page_size)
            try:
                self.paginator.page = paginator.page(page_number)
            except Exception:
                self.paginator.page = Page([], page_number, paginator)
            self.paginator.request = self.request
            return diversified

        female_filter = self._get_female_filter()
        scored_female = self._apply_relevance_scoring(base_qs.filter(female_filter), user)
        scored_male = self._apply_relevance_scoring(base_qs.exclude(female_filter), user)

        if gender == 'male':
            primary_qs = scored_male
            secondary_qs = scored_female
            max_watches = 2
        else:
            primary_qs = scored_female
            secondary_qs = scored_male
            max_watches = 1

        primary_target = int(round(page_size * 0.65))
        secondary_target = page_size - primary_target

        p_skip = (page_number - 1) * primary_target
        s_skip = (page_number - 1) * secondary_target

        primary_batch = self._extract_unique_diverse_pool(
            primary_qs, primary_target, p_skip, seed=seed, max_watches=max_watches
        )
        secondary_batch = self._extract_unique_diverse_pool(
            secondary_qs, secondary_target, s_skip, seed=seed
        )

        # Backfill if one pool is exhausted near catalog boundary or capped by watch throttle
        if len(primary_batch) < primary_target:
            needed = primary_target - len(primary_batch)
            extra_sec = self._extract_unique_diverse_pool(
                secondary_qs, needed, s_skip + len(secondary_batch), seed=seed
            )
            secondary_batch.extend(extra_sec)
        elif len(secondary_batch) < secondary_target:
            needed = secondary_target - len(secondary_batch)
            extra_prim = self._extract_unique_diverse_pool(
                primary_qs, needed, p_skip + len(primary_batch), seed=seed, max_watches=max_watches
            )
            primary_batch.extend(extra_prim)

        # Interleave primary and secondary with watch throttling and brand diversity
        interleaved = self._interleave_diverse(primary_batch, secondary_batch)

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
        if getattr(self.paginator, 'seed', None) is not None:
            response.data['seed'] = self.paginator.seed
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


