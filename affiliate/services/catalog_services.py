import hashlib
import logging
from typing import List, Dict, Any, Optional, Set
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from django.conf import settings
from django.db.models import (
    Q, Count, Case, When, Value, F, ExpressionWrapper, DecimalField, QuerySet
)
from affiliate.models import AffiliateProduct, ProductFavorite

logger = logging.getLogger(__name__)

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


def is_usable_web_url(url: str) -> bool:
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


def get_ip_prefix(request) -> str:
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


def get_ua_hash(request) -> str:
    """Compute SHA-256 hash of the client User-Agent."""
    ua = request.META.get('HTTP_USER_AGENT', '')
    return hashlib.sha256(ua.encode('utf-8')).hexdigest() if ua else ''


def build_affiliate_url(product: AffiliateProduct, click=None, click_ref=None, surface: str = 'for_you') -> str:
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
        if is_usable_web_url(merchant_link):
            if product.source == AffiliateProduct.SOURCE_AWIN:
                publisher_id = getattr(settings, 'AWIN_PUBLISHER_ID', None) or '2612792'
                encoded_url = quote(merchant_link, safe='')
                raw_link = f'https://www.awin1.com/cread.php?awinaffid={publisher_id}&ued={encoded_url}'
            elif product.source == AffiliateProduct.SOURCE_RAKUTEN:
                rakuten_id = getattr(settings, 'RAKUTEN_PUBLISHER_ID', None) or getattr(settings, 'RAKUTEN_PUBLISHER_SID', None) or '7OwTtzNBeMo'
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
        logger.warning(f"Error appending attribution to link: {e}")
        return raw_link


def get_catalog_queryset(query_params: Dict[str, Any]) -> QuerySet:
    """
    Constructs an optimized, filtered queryset for the affiliate catalog newsfeed.

    Optimizations:
    - select_related('brand_ref'): Completely eliminates N+1 queries when accessing brand metadata.
    - defer('raw_payload'): Prevents loading massive unused raw JSON/payload into memory.
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

    search    = query_params.get('search')
    brand     = query_params.get('brand')
    category  = query_params.get('category')
    colour    = query_params.get('colour')
    min_price = query_params.get('min_price')
    max_price = query_params.get('max_price')
    ordering  = query_params.get('ordering')
    source    = query_params.get('source')

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
        except (ValueError, TypeError):
            pass

    if max_price:
        try:
            qs = qs.filter(price__lte=float(max_price))
        except (ValueError, TypeError):
            pass

    if ordering == 'discount':
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


def annotate_catalog_favorites(products: List[AffiliateProduct], user) -> Set[int]:
    """
    Batch loads favorites counts and user favorite IDs in 2 atomic queries.
    Prevents N+1 database bottlenecks during pagination rendering.
    """
    if not products:
        return set()

    page_ids = [p.id for p in products]

    # Query 1: Bulk aggregation of total favorites per product ID
    fav_counts = dict(
        ProductFavorite.objects.filter(product_id__in=page_ids)
        .values('product_id')
        .annotate(c=Count('id'))
        .values_list('product_id', 'c')
    )
    for p in products:
        p._favorites_count = fav_counts.get(p.id, 0)

    # Query 2: Single lookup of current user's loved product IDs in this page
    user_fav_ids: Set[int] = set()
    if user and user.is_authenticated:
        user_fav_ids = set(
            ProductFavorite.objects.filter(
                user=user,
                product_id__in=page_ids
            ).values_list('product_id', flat=True)
        )

    return user_fav_ids


def get_catalog_brands(source: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Aggregates unique active brands and item counts for catalog navigation.
    """
    qs = AffiliateProduct.objects.filter(is_active=True)
    if source in ('awin', 'rakuten', 'shopify', 'myc_feed'):
        qs = qs.filter(source=source)

    brands_raw = (
        qs.order_by('brand')
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

    return sorted(merged.values(), key=lambda x: x['brand'].lower())


def get_catalog_categories() -> List[Dict[str, Any]]:
    """
    Aggregates unique active categories and item counts for catalog navigation.
    """
    return list(
        AffiliateProduct.objects
        .filter(is_active=True)
        .exclude(category='')
        .order_by('category')
        .values('category')
        .annotate(product_count=Count('id'))
    )
