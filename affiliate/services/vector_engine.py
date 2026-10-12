"""
affiliate/services/vector_engine.py
====================================
Vector recommendation and style profile learning engine using pgvector (AC-01 / V1-API-03 / F2).
Features:
- Incremental taste vector learning via Exponential Moving Average (EMA).
- pgvector cosine distance nearest neighbor retrieval using HNSW index.
- Style Sprint daily 10-card deck generation with brand diversity and session determinism.
- Safe fallback when embeddings are uncomputed or pgvector is uninstalled.
"""

import math, random, logging
from typing import List, Optional, Tuple, Dict
from zoneinfo import ZoneInfo

from django.db import models
from django.utils import timezone
from django.conf import settings

from affiliate.models import AffiliateProduct, ProductEmbedding, Event
from users.models import StyleProfile

try:
    from pgvector.django import CosineDistance
except ImportError:
    CosineDistance = None

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")

DEFAULT_DIMENSIONS = 768
DEFAULT_ALPHA = 0.10

# Action weights for taste vector learning
ACTION_WEIGHTS = {
    "like": 3.0,
    "right": 3.0,
    "love": 3.0,
    "save": 5.0,
    "up": 5.0,
    "favorite": 5.0,
    "click": 2.0,
    "detail": 1.5,
    "skip": -0.5,
    "left": -0.5,
    "dislike": -0.5,
}


def normalize_vector(vec: List[float]) -> List[float]:
    """L2 normalizes a float vector to unit length (||v||_2 = 1.0)."""
    if not vec:
        return vec
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return [1.0 / math.sqrt(len(vec))] * len(vec)
    return [x / norm for x in vec]


def update_user_taste_vector(
    user,
    product_id: int,
    action: str,
    alpha: float = DEFAULT_ALPHA,
) -> Optional[StyleProfile]:
    """
    Updates the user's 768-dimensional StyleProfile taste vector using EMA.
    V_user^(t+1) = Normalize( (1 - α) * V_user^(t) + α * (weight * V_prod) )
    """
    if not user or not user.is_authenticated:
        return None

    try:
        profile, _ = StyleProfile.objects.get_or_create(
            user=user, defaults={"vector_version": "fashion-siglip-v1"}
        )
    except Exception as e:
        logger.warning(f"Could not get/create StyleProfile for user {user.id}: {e}")
        return None

    try:
        prod_embed = ProductEmbedding.objects.filter(product_id=product_id).first()
    except Exception as e:
        logger.warning(f"Error fetching ProductEmbedding for product {product_id}: {e}")
        prod_embed = None

    if not prod_embed or not prod_embed.embedding:
        # Increment interaction count even without embedding for statistics
        profile.interaction_count = models.F("interaction_count") + 1
        profile.last_calculated_at = timezone.now()
        profile.save(
            update_fields=["interaction_count", "last_calculated_at", "updated_at"]
        )
        profile.refresh_from_db(fields=["interaction_count"])
        return profile

    prod_vec = list(prod_embed.embedding)
    action_clean = str(action).strip().lower()
    weight = ACTION_WEIGHTS.get(action_clean, 1.0)

    current_vec = profile.taste_vector
    if current_vec is not None:
        current_vec = list(current_vec)

    if not current_vec or len(current_vec) != len(prod_vec):
        # Cold start or dimension migration: initialize with the normalized product vector
        new_vec = normalize_vector(prod_vec)
    else:
        # EMA update step: (1 - alpha) * V_user + alpha * (weight * V_prod)
        new_vec = []
        for u_val, p_val in zip(current_vec, prod_vec):
            combined = (1.0 - alpha) * u_val + alpha * (weight * p_val)
            new_vec.append(combined)
        new_vec = normalize_vector(new_vec)

    profile.taste_vector = new_vec
    profile.interaction_count = (profile.interaction_count or 0) + 1
    profile.last_calculated_at = timezone.now()
    profile.save(
        update_fields=[
            "taste_vector",
            "interaction_count",
            "last_calculated_at",
            "updated_at",
        ]
    )
    return profile


def get_style_sprint_deck(
    user,
    berlin_date=None,
    deck_size: int = 10,
) -> Tuple[List[AffiliateProduct], int, bool]:
    """
    Generates the personalized daily 10-card swipe deck for today.
    Returns: (cards, swiped_count, is_completed)
    """
    if berlin_date is None:
        berlin_date = timezone.now().astimezone(BERLIN_TZ).date()

    # Determine cards already swiped by user today on the Style Sprint surface
    swiped_ids = set()
    if user and user.is_authenticated:
        swiped_ids = set(
            Event.objects.filter(
                user=user,
                source="sprint",
                berlin_day=berlin_date,
            ).values_list("product_id", flat=True)
        )

    swiped_count = len(swiped_ids)
    if swiped_count >= deck_size:
        return [], swiped_count, True

    needed_count = deck_size - swiped_count

    # Base candidate pool: strictly EUR currency, in stock, price > 0, active
    feed_currencies = getattr(settings, "MYC_FEED_CURRENCIES", ["EUR"])
    base_qs = AffiliateProduct.objects.filter(
        is_active=True,
        price__gt=0,
        currency__in=feed_currencies,
    ).exclude(
        models.Q(aw_deep_link__contains="awinmid=99999")
        | models.Q(aw_product_id__startswith="closly_")
        | models.Q(aw_product_id__startswith="mock_")
        | models.Q(id__in=swiped_ids)
    )

    # Exclude user's saved/favorited items
    if user and user.is_authenticated:
        base_qs = base_qs.exclude(favorites__user=user)
        # Exclude digital wardrobe items if user owns them
        try:
            from closet.models import ClosetItem

            closet_names = list(
                ClosetItem.objects.filter(user=user).values_list("name", flat=True)[
                    :100
                ]
            )
            if closet_names:
                base_qs = base_qs.exclude(name__in=closet_names)
        except Exception:
            pass

    # Check for user Taste Vector
    taste_vector = None
    if user and user.is_authenticated:
        try:
            profile = getattr(user, "style_profile", None)
            if profile and profile.taste_vector:
                taste_vector = list(profile.taste_vector)
        except Exception:
            pass

    candidate_products = []

    # 1. Try Vector Nearest Neighbor search via pgvector if taste_vector exists
    if taste_vector and CosineDistance is not None:
        try:
            vector_qs = (
                ProductEmbedding.objects.filter(product__in=base_qs)
                .annotate(distance=CosineDistance("embedding", taste_vector))
                .order_by("distance")
                .select_related("product")[:80]
            )
            candidate_products = [pe.product for pe in vector_qs]
        except Exception as e:
            logger.warning(f"Vector search failed in StyleSprint: {e}")
            candidate_products = []

    # 2. Supplement or fallback to diversified popular items
    if len(candidate_products) < needed_count * 3:
        fallback_qs = list(base_qs.order_by("-updated_at")[:100])
        existing_pids = {p.id for p in candidate_products}
        for p in fallback_qs:
            if p.id not in existing_pids:
                candidate_products.append(p)

    # 3. Deterministic deck sampling for user + date
    seed_key = (
        f"sprint_{user.id if user and user.is_authenticated else 'anon'}_{berlin_date}"
    )
    rng = random.Random(seed_key)

    # Group candidates by brand to enforce diversity (max 2 per brand in deck)
    brand_counts: Dict[str, int] = {}
    selected_deck: List[AffiliateProduct] = []

    # Shuffle candidates deterministically
    candidate_indices = list(range(len(candidate_products)))
    rng.shuffle(candidate_indices)

    for idx in candidate_indices:
        prod = candidate_products[idx]
        b_name = (prod.brand or "Other").strip().lower()
        if brand_counts.get(b_name, 0) < 2:
            selected_deck.append(prod)
            brand_counts[b_name] = brand_counts.get(b_name, 0) + 1
            if len(selected_deck) >= needed_count:
                break

    # If brand diversity filter was too strict and we need more cards, fill up
    if len(selected_deck) < needed_count:
        selected_pids = {p.id for p in selected_deck}
        for idx in candidate_indices:
            prod = candidate_products[idx]
            if prod.id not in selected_pids:
                selected_deck.append(prod)
                if len(selected_deck) >= needed_count:
                    break

    return selected_deck, swiped_count, False
