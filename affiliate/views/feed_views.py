import re
import random
import hashlib
from collections import defaultdict
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator, Page
from django.db.models import (
    Q, Count, Case, When, Value, IntegerField, F, ExpressionWrapper, DecimalField
)
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductFavorite, Event
from affiliate.serializers import AffiliateProductListSerializer

BERLIN_TZ = ZoneInfo("Europe/Berlin")


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
    Pagination class for the 'For You' discovery feed.
    Carries the discovery seed in pagination links (seed=<int>) so infinite scrolling
    remains completely non-repetitive across pages, while fresh requests without seed
    (or with refresh=true) produce a freshly seeded discovery sequence.
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
    GET /api/affiliate/products/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        feed_currencies = getattr(settings, 'MYC_FEED_CURRENCIES', ['EUR'])
        qs = AffiliateProduct.objects.filter(
            is_active=True,
            price__gt=0,
            currency__in=feed_currencies,
        ).exclude(
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
        source    = self.request.query_params.get('source')

        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(brand__icontains=search) |
                Q(description__icontains=search)
            )

        if brand:
            qs = qs.filter(brand__iexact=brand)

        if category:
            qs = qs.filter(Q(category__icontains=category) | Q(category_norm__icontains=category))

        if colour:
            qs = qs.filter(Q(colour__icontains=colour) | Q(color_primary__icontains=colour))

        if source in ('awin', 'rakuten', 'shopify', 'myc_feed'):
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

        if ordering == 'discount':
            # Fix CF-23: Calculate real discount percent and order descending
            qs = qs.annotate(
                calc_discount=Case(
                    When(
                        rrp_price__gt=F('price'),
                        then=ExpressionWrapper(
                            ((F('rrp_price') - F('price')) * 100.0) / F('rrp_price'),
                            output_field=DecimalField(max_digits=5, decimal_places=2)
                        )
                    ),
                    default=Value(0.0),
                    output_field=DecimalField(max_digits=5, decimal_places=2)
                )
            ).order_by('-calc_discount', '-price', '-created_at')
        elif ordering == 'price_asc':
            qs = qs.order_by('price')
        elif ordering == 'price_desc':
            qs = qs.order_by('-price')
        else:
            qs = qs.order_by('-created_at')

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


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Personalized 'For You' Products Feed",
    description=(
        "Curated affiliate discovery feed customized by behavioral interaction signals, "
        "taste profile, gender preference, greedy brand diversity, and cached stable pagination."
    ),
    parameters=[
        OpenApiParameter('seed', int, description="Discovery seed for deterministic pagination continuity"),
        OpenApiParameter('refresh', bool, description="Set to true to generate a freshly randomized curation seed"),
    ],
    responses={
        200: AffiliateProductListSerializer(many=True),
    }
)
class AffiliateProductForYouView(generics.ListAPIView):
    """
    GET /api/affiliate/products/for-you/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = ForYouPagination

    @staticmethod
    def _base_model_name(name: str) -> str:
        s = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
        s = re.sub(
            r'\s*-\s*(?:black|white|grey|gray|navy|olive|blue|red|green|brown|beige|tan|pink|orange|khaki|cream|burgundy|yellow)\b.*$',
            '',
            s,
            flags=re.IGNORECASE,
        ).strip()
        return s.lower()

    @staticmethod
    def _is_watch(p) -> bool:
        b = (getattr(p, 'brand', '') or '').lower()
        n = (getattr(p, 'name', '') or '').lower()
        c = (getattr(p, 'category', '') or '').lower()
        return 'd1 milano' in b or 'watch' in n or 'montre' in n or 'reloj' in n or 'uhr' in n or 'watch' in c

    def _get_clean_base_queryset(self, user=None):
        feed_currencies = getattr(settings, 'MYC_FEED_CURRENCIES', ['EUR'])
        qs = AffiliateProduct.objects.filter(
            is_active=True,
            price__gt=0,
            currency__in=feed_currencies,
        ).exclude(
            Q(aw_deep_link__contains='awinmid=99999') |
            Q(aw_product_id__startswith='closly_') |
            Q(aw_product_id__startswith='mock_')
        )

        # Exclude saved products per product spec
        if user and user.is_authenticated:
            qs = qs.exclude(favorites__user=user)

        # Gender preference filtering (removing hardcoded 65/35 developer invention)
        user_gender = getattr(user, 'gender', None) if user and user.is_authenticated else None
        if user_gender:
            user_gender = user_gender.lower()
            if user_gender in ('female', 'women'):
                qs = qs.filter(gender__in=['women', 'unisex'])
            elif user_gender in ('male', 'men'):
                qs = qs.filter(gender__in=['men', 'unisex'])

        return qs

    def _get_user_behavior_boosts(self, user):
        """
        Aggregate behavioral recommendation scores from recent Events (NO LLM).
        Weights are configured in settings.MYC_EVENT_WEIGHTS.
        """
        if not user or not user.is_authenticated:
            return defaultdict(float), defaultdict(float), defaultdict(float)

        brand_boosts = defaultdict(float)
        category_boosts = defaultdict(float)
        color_boosts = defaultdict(float)

        event_weights = getattr(settings, 'MYC_EVENT_WEIGHTS', {})

        # 1. Recent behavioral events (last 500 events)
        recent_events = (
            Event.objects.filter(user=user)
            .select_related('product')
            .order_by('-created_at')[:500]
        )
        for ev in recent_events:
            w = event_weights.get(ev.event_type, 1.0)
            if ev.dwell_ms and ev.dwell_ms >= 5000:
                w += event_weights.get('long_view', 2.0)

            prod = ev.product
            if prod:
                if prod.brand:
                    brand_boosts[prod.brand.strip().lower()] += w
                if prod.category_norm:
                    category_boosts[prod.category_norm.strip().lower()] += w
                if prod.color_primary:
                    color_boosts[prod.color_primary.strip().lower()] += w

        # 2. Closet affinity brands
        try:
            from closet.models import ClosetItem
            closet_brands = list(
                ClosetItem.objects.filter(user=user)
                .exclude(Q(brand='') | Q(brand__iexact='N/A'))
                .order_by('-created_at')
                .values_list('brand', flat=True)[:30]
            )
            for cb in closet_brands:
                if cb:
                    brand_boosts[cb.strip().lower()] += 10.0
        except Exception:
            pass

        # 3. User onboarding preferences
        if hasattr(user, 'preferences'):
            prefs = user.preferences
            for pb in (prefs.preferred_brands or []):
                if pb and pb.strip():
                    brand_boosts[pb.strip().lower()] += 25.0

            palette = prefs.color_palette or ''
            palette_map = {
                'neutral_minimalist': ['black', 'white', 'grey', 'gray', 'beige', 'navy', 'cream'],
                'bold_rich': ['red', 'blue', 'green', 'yellow', 'purple', 'burgundy', 'orange'],
                'soft_romantic': ['pink', 'pastel', 'lavender', 'rose', 'peach', 'mint', 'blush'],
                'earthy_warm': ['brown', 'tan', 'olive', 'khaki', 'terracotta', 'rust', 'camel'],
            }
            for col in palette_map.get(palette, []):
                color_boosts[col] += 15.0

            if isinstance(prefs.clothing_categories, dict):
                for sublist in prefs.clothing_categories.values():
                    if isinstance(sublist, list):
                        for ckw in sublist:
                            category_boosts[ckw.lower()] += 15.0

        return brand_boosts, category_boosts, color_boosts

    def _apply_relevance_scoring(self, qs, user):
        if not user or not user.is_authenticated:
            return qs.order_by('-id')

        brand_boosts, category_boosts, color_boosts = self._get_user_behavior_boosts(user)

        score_cases = []

        # Top 15 brands by affinity
        top_brands = sorted(brand_boosts.items(), key=lambda x: x[1], reverse=True)[:15]
        for b_name, b_score in top_brands:
            score_cases.append(
                When(brand__iexact=b_name, then=Value(int(round(b_score))))
            )

        # Top 10 categories
        top_categories = sorted(category_boosts.items(), key=lambda x: x[1], reverse=True)[:10]
        for c_name, c_score in top_categories:
            score_cases.append(
                When(
                    Q(category_norm__iexact=c_name) | Q(category__icontains=c_name),
                    then=Value(int(round(c_score)))
                )
            )

        # Top 10 colors
        top_colors = sorted(color_boosts.items(), key=lambda x: x[1], reverse=True)[:10]
        for col_name, col_score in top_colors:
            score_cases.append(
                When(
                    Q(color_primary__iexact=col_name) | Q(colour__icontains=col_name),
                    then=Value(int(round(col_score)))
                )
            )

        if score_cases:
            return qs.annotate(
                relevance_score=Case(*score_cases, default=Value(0), output_field=IntegerField())
            ).order_by('-relevance_score', '-id')

        return qs.order_by('-id')

    def _generate_ordered_discovery_feed(self, user, seed: int) -> list:
        """
        Generate full ordered candidate list for (user, seed).
        Applies single candidate pool, deduplication, and greedy brand diversity.
        """
        candidate_limit = getattr(settings, 'MYC_FEED_CANDIDATES', 600)
        base_qs = self._get_clean_base_queryset(user)
        scored_qs = self._apply_relevance_scoring(base_qs, user)

        candidates = list(scored_qs[:candidate_limit])
        if not candidates:
            return []

        # 1. Deduplication by (brand, base_model_name) and (brand, image_url)
        seen_models = set()
        seen_images = set()
        deduped = []

        for p in candidates:
            brand_clean = (p.brand or '').strip().lower()
            model_key = (brand_clean, self._base_model_name(p.name))
            img_key = (brand_clean, p.image_url.strip()) if p.image_url else None

            if model_key in seen_models:
                continue
            if img_key and img_key in seen_images:
                continue

            seen_models.add(model_key)
            if img_key:
                seen_images.add(img_key)

            deduped.append(p)

        # 2. Seeded deterministic shuffle within score tiers
        tiers = defaultdict(list)
        for p in deduped:
            score = getattr(p, 'relevance_score', 0) or 0
            tiers[score].append(p)

        shuffled = []
        for score in sorted(tiers.keys(), reverse=True):
            items_in_tier = list(tiers[score])
            tier_seed = (int(seed) + int(score) * 7919) % 2147483647
            rng = random.Random(tier_seed)
            rng.shuffle(items_in_tier)
            shuffled.extend(items_in_tier)

        # 3. Greedy diversity pass:
        # - Max 3 per brand in 20-product window
        # - Max 30% from one brand in 100-product window
        # - Prevent adjacent same-brand products
        # - Max 2 watches per 20 items
        max_brand_20 = getattr(settings, 'MYC_FEED_MAX_SAME_BRAND_WINDOW_20', 3)
        max_brand_100_ratio = getattr(settings, 'MYC_FEED_MAX_BRAND_SHARE_WINDOW_100', 0.30)

        ordered = []
        source_pool = list(shuffled)

        while source_pool:
            last_brand = (ordered[-1].brand or '').strip().lower() if ordered else None
            last_was_watch = self._is_watch(ordered[-1]) if ordered else False

            # Check window counts
            recent_20 = ordered[-20:]
            recent_20_brands = defaultdict(int)
            recent_20_watches = 0
            for item in recent_20:
                recent_20_brands[(item.brand or '').strip().lower()] += 1
                if self._is_watch(item):
                    recent_20_watches += 1

            recent_100 = ordered[-100:]
            recent_100_brands = defaultdict(int)
            for item in recent_100:
                recent_100_brands[(item.brand or '').strip().lower()] += 1

            picked_idx = None

            # Pass 1: Strict brand cap & watch constraints
            for idx, cand in enumerate(source_pool):
                cand_brand = (cand.brand or '').strip().lower()
                cand_is_watch = self._is_watch(cand)

                # Avoid adjacent same-brand items
                if cand_brand == last_brand and len(source_pool) > 1:
                    continue
                # Cap max 3 items per brand in 20-product window
                if recent_20_brands[cand_brand] >= max_brand_20:
                    continue
                # Cap max 30% from one brand in 100-product window
                if len(recent_100) >= 30 and (recent_100_brands[cand_brand] / len(recent_100)) >= max_brand_100_ratio:
                    continue
                # Watch spacing & limit
                if cand_is_watch and (recent_20_watches >= 2 or last_was_watch):
                    continue

                picked_idx = idx
                break

            # Pass 2: Relax window caps if remaining pool has no brand satisfying Pass 1
            if picked_idx is None:
                for idx, cand in enumerate(source_pool):
                    cand_brand = (cand.brand or '').strip().lower()
                    cand_is_watch = self._is_watch(cand)
                    if cand_brand == last_brand and len(source_pool) > 1:
                        continue
                    if cand_is_watch and last_was_watch:
                        continue
                    picked_idx = idx
                    break

            # Pass 3: Ultimate fallback
            if picked_idx is None:
                picked_idx = 0

            chosen = source_pool.pop(picked_idx)
            ordered.append(chosen)

        return [p.id for p in ordered]

    def _get_or_create_cached_feed_ids(self, user, seed: int, refresh: bool) -> list:
        user_key = f"user_{user.id}" if user and user.is_authenticated else "anon"
        cache_key = f"feed:{user_key}:{seed}"

        if not refresh:
            cached_ids = cache.get(cache_key)
            if cached_ids is not None:
                return cached_ids

        ordered_ids = self._generate_ordered_discovery_feed(user, seed)
        ttl = getattr(settings, 'MYC_FEED_CACHE_TTL', 93600)
        cache.set(cache_key, ordered_ids, timeout=ttl)
        return ordered_ids

    def get_queryset(self):
        return self._get_clean_base_queryset(self.request.user)

    def paginate_queryset(self, queryset):
        user = self.request.user

        page_size = self.paginator.get_page_size(self.request) or getattr(self.paginator, 'page_size', 20) or 20
        page_number_str = self.request.query_params.get(self.paginator.page_query_param, 1)
        try:
            page_number = int(page_number_str)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1

        seed_param = self.request.query_params.get('seed')
        refresh_param = self.request.query_params.get('refresh', '').lower() in ('true', '1', 'yes')

        if refresh_param or not seed_param or (page_number == 1 and not seed_param):
            seed = random.randint(100000, 999999)
        else:
            try:
                seed = int(seed_param)
            except (ValueError, TypeError):
                # Deterministic SHA-256 hash instead of process-dependent hash()
                seed = int(hashlib.sha256(str(seed_param).encode('utf-8')).hexdigest()[:8], 16) % 1000000

        if hasattr(self.paginator, 'seed'):
            self.paginator.seed = seed

        # Get or generate cached ordered product IDs
        ordered_ids = self._get_or_create_cached_feed_ids(user, seed, refresh=refresh_param)

        total_count = len(ordered_ids)
        paginator = Paginator(range(total_count), page_size)
        try:
            self.paginator.page = paginator.page(page_number)
        except Exception:
            self.paginator.page = Page([], page_number, paginator)
        self.paginator.request = self.request

        start_idx = (page_number - 1) * page_size
        end_idx = start_idx + page_size
        page_ids = ordered_ids[start_idx:end_idx]

        if not page_ids:
            return []

        # Fetch products preserving exact order of page_ids
        products = list(AffiliateProduct.objects.filter(id__in=page_ids))
        prod_map = {p.id: p for p in products}
        ordered_page = [prod_map[pid] for pid in page_ids if pid in prod_map]

        return ordered_page

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
        is_personalized = bool(user and user.is_authenticated)

        prefs_summary = None
        if is_personalized and hasattr(user, 'preferences'):
            prefs = user.preferences
            prefs_summary = {
                'palette': prefs.color_palette or 'neutral_minimalist',
                'styles': prefs.style_match or ['minimalist'],
                'preferred_brands': prefs.preferred_brands or []
            }

        response.data['user_taste_profile'] = prefs_summary
        response.data['personalized'] = is_personalized
        if getattr(self.paginator, 'seed', None) is not None:
            response.data['seed'] = self.paginator.seed

        if is_personalized:
            response.data['message'] = "Personalized 'For You' discovery feed curated based on your taste profile and behavioral signals."
        else:
            response.data['message'] = "Discover trending fashion items. Sign in to personalize your discovery feed."

        return response
