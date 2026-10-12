"""
affiliate/services package.
Provides discovery ranking, catalog querying, telemetry ingestion,
image caching, vector generation, and Style Sprint deck services.
"""

from .catalog_services import (
    build_affiliate_url,
    get_catalog_queryset,
    annotate_catalog_favorites,
    get_catalog_brands,
    get_catalog_categories,
    is_usable_web_url,
    get_ip_prefix,
    get_ua_hash,
)

from .discovery_services import (
    get_clean_base_queryset,
    get_user_behavior_boosts,
    apply_relevance_scoring,
    generate_ordered_discovery_feed,
    get_or_create_cached_feed_ids,
    get_for_you_feed_page,
)

from .sprint_services import (
    process_swipe_interactions,
)

from .telemetry_services import (
    queue_event_batch,
)

from .vector_engine import (
    get_style_sprint_deck,
    update_user_taste_vector,
)

from .embedding_service import (
    generate_embedding_for_product,
    batch_generate_product_embeddings,
)

__all__ = [
    'build_affiliate_url',
    'get_catalog_queryset',
    'annotate_catalog_favorites',
    'get_catalog_brands',
    'get_catalog_categories',
    'is_usable_web_url',
    'get_ip_prefix',
    'get_ua_hash',
    'get_clean_base_queryset',
    'get_user_behavior_boosts',
    'apply_relevance_scoring',
    'generate_ordered_discovery_feed',
    'get_or_create_cached_feed_ids',
    'get_for_you_feed_page',
    'process_swipe_interactions',
    'queue_event_batch',
    'get_style_sprint_deck',
    'update_user_taste_vector',
    'generate_embedding_for_product',
    'batch_generate_product_embeddings',
]
