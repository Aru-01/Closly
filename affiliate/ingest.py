import re
import decimal
import hashlib
from typing import Dict, Any, List, Optional
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, F
from affiliate.models import (
    AffiliateProduct,
    Brand,
    CatalogSyncRun,
    FeedAttributeMapping,
)


def _tokenized_match(text: str, token: str) -> bool:
    """Safe tokenized match using word boundaries to prevent false substring matches (e.g. 'cos' in 'lacoste')."""
    if not text or not token:
        return False
    pattern = r'\b' + re.escape(token.strip().lower()) + r'\b'
    return bool(re.search(pattern, text.lower()))


# Cache for feed attribute mappings to avoid querying DB per row
_MAPPING_CACHE: Dict[str, Dict[str, str]] = {}
_MAPPING_CACHE_LOADED_AT = None


def get_attribute_mappings(field: str) -> Dict[str, str]:
    """Retrieve attribute mappings for category/gender/color with in-memory caching."""
    global _MAPPING_CACHE, _MAPPING_CACHE_LOADED_AT
    now = timezone.now()
    if _MAPPING_CACHE_LOADED_AT is None or (now - _MAPPING_CACHE_LOADED_AT).total_seconds() > 300:
        _MAPPING_CACHE = {}
        for m in FeedAttributeMapping.objects.all():
            fld = m.field.lower()
            if fld not in _MAPPING_CACHE:
                _MAPPING_CACHE[fld] = {}
            _MAPPING_CACHE[fld][m.raw_value.strip().lower()] = m.normalized_value
        _MAPPING_CACHE_LOADED_AT = now

    return _MAPPING_CACHE.get(field.lower(), {})


def normalize_gender(raw_category: str, raw_name: str, brand_name: str = '') -> str:
    """
    Ingest-time gender normalization using attribute mappings and tokenized keywords.
    Returns: 'women', 'men', or 'unisex'.
    """
    mappings = get_attribute_mappings('gender')

    combined_text = f"{raw_category} {raw_name}".lower()

    # Exact mapping check
    for raw_val, mapped_gender in mappings.items():
        if _tokenized_match(combined_text, raw_val):
            return mapped_gender

    women_tokens = [
        'women', 'womenswear', 'damen', 'femme', 'dress', 'skirt', 'blouse',
        'bra', 'bralette', 'lingerie', 'maternity', 'robe', 'mini-jupe', 'kleid', 'rock'
    ]
    men_tokens = [
        'men', 'menswear', 'herren', 'homme', 'hemd', 'suit', 'anzug'
    ]

    for wt in women_tokens:
        if _tokenized_match(combined_text, wt):
            return AffiliateProduct.GENDER_WOMEN

    for mt in men_tokens:
        if _tokenized_match(combined_text, mt):
            return AffiliateProduct.GENDER_MEN

    return AffiliateProduct.GENDER_UNISEX


def normalize_category(raw_category: str, raw_name: str) -> str:
    """
    Ingest-time category normalization using attribute mappings.
    Returns standard taxonomy category (e.g. 'Dresses', 'Tops', 'Shoes', etc.).
    """
    mappings = get_attribute_mappings('category')

    raw_clean = (raw_category or '').strip().lower()
    if raw_clean in mappings:
        return mappings[raw_clean]

    combined = f"{raw_category} {raw_name}".lower()
    for raw_val, norm_val in mappings.items():
        if _tokenized_match(combined, raw_val):
            return norm_val

    # Fallback to direct raw category string if non-empty
    return raw_category.strip()[:255] if raw_category else 'Other'


def normalize_color(raw_color: str, raw_name: str) -> str:
    """
    Ingest-time color normalization.
    """
    raw_clean = (raw_color or '').strip().lower()
    if raw_clean:
        return raw_clean[:100]

    colors = [
        'black', 'white', 'grey', 'gray', 'beige', 'navy', 'cream', 'blue',
        'red', 'green', 'brown', 'tan', 'pink', 'orange', 'khaki', 'burgundy', 'yellow'
    ]
    name_lower = (raw_name or '').lower()
    for col in colors:
        if _tokenized_match(name_lower, col):
            return col
    return ''


def compute_content_hash(
    name: str,
    price: decimal.Decimal,
    rrp_price: Optional[decimal.Decimal],
    brand: str,
    image_url: str,
    is_active: bool,
    currency: str,
) -> str:
    """Compute deterministic SHA-256 content hash of product payload for change detection."""
    payload = f"{name.strip()}|{price}|{rrp_price}|{brand.strip()}|{image_url.strip()}|{is_active}|{currency.strip()}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def flush_catalog_batch(
    rows: List[Dict[str, Any]],
    sync_time,
    source: str,
    brand_cache: Dict[str, Brand],
) -> Dict[str, int]:
    """
    Upsert batch of products with change detection.
    Rows with matching content_hash only have last_seen_at refreshed (0 DB column churn).
    """
    if not rows:
        return {'new': 0, 'changed': 0, 'unchanged': 0}

    # Deduplicate in-memory by aw_product_id
    deduped: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        deduped[r['aw_product_id']] = r

    product_ids = list(deduped.keys())

    existing_rows = {
        p.aw_product_id: p
        for p in AffiliateProduct.objects.filter(aw_product_id__in=product_ids).only('id', 'aw_product_id', 'content_hash')
    }

    instances_to_create = []
    instances_to_update = []
    unchanged_ids = []

    for network_id, r in deduped.items():
        brand_name = r.get('brand', '').strip()
        brand_obj = brand_cache.get(brand_name.lower())

        chash = r['content_hash']
        existing = existing_rows.get(network_id)

        if existing:
            if existing.content_hash == chash:
                # Content identical — record last_seen_at update only
                unchanged_ids.append(existing.id)
            else:
                # Content changed
                inst = AffiliateProduct(
                    id=existing.id,
                    aw_product_id=network_id,
                    source=source,
                    brand_ref=brand_obj,
                    name=r['name'],
                    brand=brand_name,
                    description=r.get('description', ''),
                    price=r['price'],
                    rrp_price=r.get('rrp_price'),
                    currency=r['currency'],
                    image_url=r['image_url'],
                    additional_image_urls=r.get('additional_image_urls', []),
                    aw_deep_link=r['aw_deep_link'],
                    merchant_deep_link=r.get('merchant_deep_link', ''),
                    category=r.get('category', ''),
                    category_norm=r.get('category_norm', ''),
                    gender=r.get('gender', AffiliateProduct.GENDER_UNISEX),
                    colour=r.get('colour', ''),
                    color_primary=r.get('color_primary', ''),
                    advertiser_name=r.get('advertiser_name', ''),
                    is_active=r.get('is_active', True),
                    in_stock=r.get('in_stock', True),
                    miss_count=0,
                    content_hash=chash,
                    last_seen_at=sync_time,
                )
                instances_to_update.append(inst)
        else:
            # New product
            inst = AffiliateProduct(
                aw_product_id=network_id,
                source=source,
                brand_ref=brand_obj,
                name=r['name'],
                brand=brand_name,
                description=r.get('description', ''),
                price=r['price'],
                rrp_price=r.get('rrp_price'),
                currency=r['currency'],
                image_url=r['image_url'],
                additional_image_urls=r.get('additional_image_urls', []),
                aw_deep_link=r['aw_deep_link'],
                merchant_deep_link=r.get('merchant_deep_link', ''),
                category=r.get('category', ''),
                category_norm=r.get('category_norm', ''),
                gender=r.get('gender', AffiliateProduct.GENDER_UNISEX),
                colour=r.get('colour', ''),
                color_primary=r.get('color_primary', ''),
                advertiser_name=r.get('advertiser_name', ''),
                is_active=r.get('is_active', True),
                in_stock=r.get('in_stock', True),
                miss_count=0,
                content_hash=chash,
                first_seen_at=sync_time,
                last_seen_at=sync_time,
            )
            instances_to_create.append(inst)

    new_count = len(instances_to_create)
    changed_count = len(instances_to_update)
    unchanged_count = len(unchanged_ids)

    update_fields = [
        'brand_ref', 'name', 'brand', 'description', 'price',
        'rrp_price', 'currency', 'image_url', 'additional_image_urls',
        'aw_deep_link', 'merchant_deep_link', 'category', 'category_norm',
        'gender', 'colour', 'color_primary', 'advertiser_name',
        'is_active', 'in_stock', 'miss_count', 'content_hash', 'last_seen_at',
    ]

    with transaction.atomic():
        if instances_to_create:
            AffiliateProduct.objects.bulk_create(instances_to_create, batch_size=1000)

        if instances_to_update:
            AffiliateProduct.objects.bulk_update(instances_to_update, update_fields, batch_size=1000)

        if unchanged_ids:
            AffiliateProduct.objects.filter(id__in=unchanged_ids).update(
                last_seen_at=sync_time,
                miss_count=0,
                is_active=True,
            )

    return {
        'new': new_count,
        'changed': changed_count,
        'unchanged': unchanged_count,
    }


def apply_stale_deactivation_guard(
    sync_run: CatalogSyncRun,
    active_before: int,
    source: str,
    sync_time,
    extra_filter: Optional[dict] = None,
) -> int:
    """
    Applies zero-delta safety threshold and 2-run miss-count grace period.
    Returns count of deactivated products.
    """
    threshold_ratio = getattr(settings, 'MYC_SYNC_ZERO_DELTA_THRESHOLD', 0.5)
    miss_threshold = getattr(settings, 'MYC_SYNC_MISS_COUNT_THRESHOLD', 2)

    # 1. Zero-delta / Suspicious feed check
    if active_before > 0 and (sync_run.rows_seen < active_before * threshold_ratio):
        sync_run.status = CatalogSyncRun.STATUS_GUARDED
        sync_run.notes += (
            f" [GUARDED]: Suspicious feed. Rows seen ({sync_run.rows_seen}) < "
            f"{threshold_ratio * 100}% of active products before sync ({active_before}). "
            f"Skipped deactivation to protect catalogue."
        )
        sync_run.save(update_fields=['status', 'notes', 'finished_at'])
        return 0

    # 2. Query products not seen in this sync run
    qs = AffiliateProduct.objects.filter(
        source=source,
        is_active=True,
    )
    if extra_filter:
        qs = qs.filter(**extra_filter)

    # Products whose last_seen_at is older than sync_time
    stale_qs = qs.filter(Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=sync_time))

    # Grace period pass:
    # 1. Products already at or above (miss_threshold - 1) consecutive misses are deactivated
    deactivated = stale_qs.filter(miss_count__gte=miss_threshold - 1).update(
        is_active=False,
        miss_count=F('miss_count') + 1,
    )

    # 2. Products missing for the first time (< miss_threshold - 1) increment miss_count and remain active
    stale_qs.filter(miss_count__lt=miss_threshold - 1, is_active=True).update(
        miss_count=F('miss_count') + 1,
    )

    return deactivated
