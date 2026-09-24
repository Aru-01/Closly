import re
import random
import operator
from functools import reduce
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django.db.models import Q, Count, Case, When, Value, IntegerField
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductFavorite
from affiliate.serializers import AffiliateProductListSerializer


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


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Affiliate Products Feed",
    description="Returns paginated affiliate products for the newsfeed with search, brand, category, colour, price, and network filters.",
    parameters=[
        OpenApiParameter('search', str, description="Search across product name, brand, description"),
        OpenApiParameter('brand', str, description="Filter by brand (exact match)"),
        OpenApiParameter('category', str, description="Filter by product category"),
        OpenApiParameter('colour', str, description="Filter by colour keyword"),
        OpenApiParameter('min_price', float, description="Minimum price filter"),
        OpenApiParameter('max_price', float, description="Maximum price filter"),
        OpenApiParameter('ordering', str, description="Sort order: 'price_asc', 'price_desc', 'newest', 'discount'"),
        OpenApiParameter('source', str, description="Filter by network: 'awin' or 'rakuten'"),
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
            'discount':   'price',
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


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Personalized 'For You' Products Feed",
    description=(
        "Curated affiliate discovery feed customized by user Style DNA, preferred brands, "
        "color palette, and gender balancing (65% primary gender / 35% secondary gender)."
    ),
    parameters=[
        OpenApiParameter('seed', int, description="Discovery seed for pagination continuity"),
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
        s = re.sub(r'\s*-\s*(?:black|white|grey|gray|navy|olive|blue|red|green|brown|beige|tan|pink|orange|khaki|cream|burgundy|yellow)\b.*$', '', s, flags=re.IGNORECASE).strip()
        return s.lower()

    def _get_clean_base_queryset(self):
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

        unisex_words = [
            'watch', 'cap', 'sunglasses', 'card case', 'cardholder', 'wallet', 'porte-cartes',
            'sneaker', 'trainer', 'basket', 'scarf', 'écharpe', 'foulard', 'belt', 'ceinture',
            'keyring', 'backpack', 'sac à dos', 'duffle', 'comb', 'blanket', 'socks',
            'recovery', 'brace', 'sleeve'
        ]
        unisex_q = Q()
        for uw in unisex_words:
            unisex_q |= Q(name__icontains=uw)

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

        affinity_brands = self._get_user_affinity_brands(user)
        if affinity_brands:
            aff_q = Q()
            for ab in list(affinity_brands)[:15]:
                aff_q |= Q(brand__iexact=ab)
            score_parts.append(Case(When(aff_q, then=Value(25)), default=Value(0), output_field=IntegerField()))

        if hasattr(user, 'preferences'):
            prefs = user.preferences
            preferred_brands = prefs.preferred_brands or []
            palette = prefs.color_palette or ''
            styles = prefs.style_match or []
            clothing_cats = prefs.clothing_categories or {}

            if preferred_brands:
                brand_q = Q()
                for b in preferred_brands:
                    if b and b.strip():
                        brand_q |= Q(brand__icontains=b.strip())
                score_parts.append(Case(When(brand_q, then=Value(40)), default=Value(0), output_field=IntegerField()))

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
        needed_total = skip_count + target_count
        candidate_limit = max(needed_total * 4, 180)

        brands_in_qs = list(qs.order_by().values_list('brand', flat=True).distinct()[:8])
        if len(brands_in_qs) > 1:
            per_brand_limit = max(candidate_limit // len(brands_in_qs), 35)
            candidates = []
            for b in brands_in_qs:
                candidates.extend(list(qs.filter(brand=b)[:per_brand_limit]))
        else:
            candidates = list(qs[:candidate_limit])

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
