import re
import random
import logging
from collections import defaultdict
from typing import List, Tuple, Set
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    Q, Case, When, Value, IntegerField, QuerySet
)
from affiliate.models import AffiliateProduct, Event

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def base_model_name(name: str) -> str:
    """Normalize product name by stripping parentheticals and color descriptors."""
    s = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    s = re.sub(
        r'\s*-\s*(?:black|white|grey|gray|navy|olive|blue|red|green|brown|beige|tan|pink|orange|khaki|cream|burgundy|yellow)\b.*$',
        '',
        s,
        flags=re.IGNORECASE,
    ).strip()
    return s.lower()


def is_watch(product: AffiliateProduct) -> bool:
    """Determine if a product is a watch for catalog spacing and diversity caps."""
    b = (getattr(product, 'brand', '') or '').lower()
    n = (getattr(product, 'name', '') or '').lower()
    c = (getattr(product, 'category', '') or '').lower()
    return 'd1 milano' in b or 'watch' in n or 'montre' in n or 'reloj' in n or 'uhr' in n or 'watch' in c


def get_clean_base_queryset(user=None) -> QuerySet:
    """
    Constructs clean base catalog queryset for discovery and recommendation engines.

    Optimizations:
    - select_related('brand_ref'): Eliminates N+1 queries when accessing foreign brand metadata.
    - defer('raw_payload'): Prevents loading huge unindexed payload dumps.
    """
    feed_currencies = getattr(settings, 'MYC_FEED_CURRENCIES', ['EUR'])
    qs = (
        AffiliateProduct.objects.filter(
            is_active=True,
            price__gt=0,
            currency__in=feed_currencies,
        )
        .exclude(
            Q(aw_deep_link__contains='awinmid=99999') |
            Q(aw_product_id__startswith='closly_') |
            Q(aw_product_id__startswith='mock_')
        )
        .select_related('brand_ref')
    )

    # Exclude saved products per product discovery spec
    if user and user.is_authenticated:
        qs = qs.exclude(favorites__user=user)

    # Gender preference filtering
    user_gender = getattr(user, 'gender', None) if user and user.is_authenticated else None
    if user_gender:
        user_gender = user_gender.lower()
        if user_gender in ('female', 'women'):
            qs = qs.filter(gender__in=['women', 'unisex'])
        elif user_gender in ('male', 'men'):
            qs = qs.filter(gender__in=['men', 'unisex'])

    return qs


def get_user_behavior_boosts(user) -> Tuple[defaultdict, defaultdict, defaultdict]:
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
        .select_related('product', 'product__brand_ref')
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


def apply_relevance_scoring(qs: QuerySet, user) -> QuerySet:
    """Applies SQL Case/When relevance scoring based on behavioral signal aggregation."""
    if not user or not user.is_authenticated:
        return qs.order_by('-id')

    brand_boosts, category_boosts, color_boosts = get_user_behavior_boosts(user)

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


def generate_ordered_discovery_feed(user, seed: int) -> List[int]:
    """
    Generate full ordered candidate list of product IDs for (user, seed).
    Applies:
    1. pgvector CosineDistance nearest-neighbor candidate retrieval if user has taste_vector.
    2. Behavioral + onboarding attribute scoring.
    3. Cold Start Fallback: Guarantees diverse catalog products if candidate pool is small.
    4. In-batch deduplication by model and image.
    5. Seeded deterministic shuffle within score tiers.
    6. Greedy brand diversity window pass (max 3/brand/20 items, max 30% brand share/100 items, max 2 watches).
    """
    candidate_limit = getattr(settings, 'MYC_FEED_CANDIDATES', 600)
    base_qs = get_clean_base_queryset(user)

    # -------------------------------------------------------------
    # Vector Nearest-Neighbor Candidate Retrieval (pgvector)
    # -------------------------------------------------------------
    vector_candidates = []
    taste_vector = None
    if user and user.is_authenticated:
        try:
            profile = getattr(user, 'style_profile', None)
            if profile and profile.taste_vector:
                taste_vector = list(profile.taste_vector)
        except Exception:
            pass

    if taste_vector:
        try:
            from pgvector.django import CosineDistance
            from affiliate.models import ProductEmbedding
            vec_qs = (
                ProductEmbedding.objects.filter(product__in=base_qs)
                .annotate(distance=CosineDistance('embedding', taste_vector))
                .order_by('distance')
                .select_related('product', 'product__brand_ref')[:200]
            )
            vector_candidates = [pe.product for pe in vec_qs if pe.product]
        except Exception as e:
            logger.warning(f"pgvector query in For-You feed failed: {e}")

    scored_qs = apply_relevance_scoring(base_qs, user)
    candidates = list(scored_qs[:candidate_limit])

    # Merge vector candidates at the top if present
    if vector_candidates:
        merged = []
        seen_ids = set()
        for vp in vector_candidates:
            setattr(vp, 'relevance_score', 80)
            merged.append(vp)
            seen_ids.add(vp.id)
        for c in candidates:
            if c.id not in seen_ids:
                merged.append(c)
                seen_ids.add(c.id)
        candidates = merged

    # -------------------------------------------------------------
    # Robust Cold Start Fallback: Guarantee feed is NEVER empty
    # -------------------------------------------------------------
    if len(candidates) < 40:
        feed_currencies = getattr(settings, 'MYC_FEED_CURRENCIES', ['EUR'])
        cold_qs = (
            AffiliateProduct.objects.filter(
                is_active=True,
                price__gt=0,
                currency__in=feed_currencies,
            )
            .exclude(
                Q(aw_deep_link__contains='awinmid=99999') |
                Q(aw_product_id__startswith='closly_') |
                Q(aw_product_id__startswith='mock_')
            )
            .select_related('brand_ref')
        )
        if user and user.is_authenticated:
            cold_qs = cold_qs.exclude(favorites__user=user)

        # Draw diverse items across live catalog
        cold_items = list(cold_qs.order_by('-updated_at')[:300])
        cand_ids = {c.id for c in candidates}
        for ci in cold_items:
            if ci.id not in cand_ids:
                setattr(ci, 'relevance_score', 10)
                candidates.append(ci)
                cand_ids.add(ci.id)

    if not candidates:
        return []

    # 1. Deduplication by (brand, base_model_name) and (brand, image_url)
    seen_models = set()
    seen_images = set()
    deduped = []

    for p in candidates:
        brand_clean = (p.brand or '').strip().lower()
        model_key = (brand_clean, base_model_name(p.name))
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
        last_was_watch = is_watch(ordered[-1]) if ordered else False

        # Check window counts
        recent_20 = ordered[-20:]
        recent_20_brands = defaultdict(int)
        recent_20_watches = 0
        for item in recent_20:
            recent_20_brands[(item.brand or '').strip().lower()] += 1
            if is_watch(item):
                recent_20_watches += 1

        recent_100 = ordered[-100:]
        recent_100_brands = defaultdict(int)
        for item in recent_100:
            recent_100_brands[(item.brand or '').strip().lower()] += 1

        picked_idx = None

        # Pass 1: Strict brand cap & watch constraints
        for idx, cand in enumerate(source_pool):
            cand_brand = (cand.brand or '').strip().lower()
            cand_is_watch = is_watch(cand)

            if cand_brand == last_brand and len(source_pool) > 1:
                continue
            if recent_20_brands[cand_brand] >= max_brand_20:
                continue
            if len(recent_100) >= 30 and (recent_100_brands[cand_brand] / len(recent_100)) >= max_brand_100_ratio:
                continue
            if cand_is_watch and (recent_20_watches >= 2 or last_was_watch):
                continue

            picked_idx = idx
            break

        # Pass 2: Relax window caps if remaining pool has no brand satisfying Pass 1
        if picked_idx is None:
            for idx, cand in enumerate(source_pool):
                cand_brand = (cand.brand or '').strip().lower()
                cand_is_watch = is_watch(cand)
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


def get_or_create_cached_feed_ids(user, seed: int, refresh: bool) -> List[int]:
    """Retrieve or compute cached deterministic candidate sequence for (user, seed)."""
    user_key = f"user_{user.id}" if user and user.is_authenticated else "anon"
    cache_key = f"feed:{user_key}:{seed}"

    if not refresh:
        cached_ids = cache.get(cache_key)
        if cached_ids is not None:
            return cached_ids

    ordered_ids = generate_ordered_discovery_feed(user, seed)
    ttl = getattr(settings, 'MYC_FEED_CACHE_TTL', 93600)
    cache.set(cache_key, ordered_ids, timeout=ttl)
    return ordered_ids


def get_for_you_feed_page(
    user,
    ordered_ids: List[int],
    page_number: int,
    page_size: int
) -> Tuple[List[AffiliateProduct], Set[int]]:
    """
    Slices the ordered product IDs for the requested page and fetches them from DB.

    CRITICAL N+1 ELIMINATION:
    - Uses select_related('brand_ref') so accessing brand relations costs 0 extra queries.
    - Preserves exact algorithmic order.
    - Annotates favorites in bulk via annotate_catalog_favorites.
    """
    start_idx = (page_number - 1) * page_size
    end_idx = start_idx + page_size
    page_ids = ordered_ids[start_idx:end_idx]

    if not page_ids:
        return [], set()

    # Optimized Query with select_related to eliminate N+1 queries
    products = list(
        AffiliateProduct.objects.filter(id__in=page_ids)
        .select_related('brand_ref')
    )
    prod_map = {p.id: p for p in products}
    ordered_page = [prod_map[pid] for pid in page_ids if pid in prod_map]

    # Bulk annotate favorites counts and user favorites
    from affiliate.services.catalog_services import annotate_catalog_favorites
    user_fav_ids = annotate_catalog_favorites(ordered_page, user)

    return ordered_page, user_fav_ids
