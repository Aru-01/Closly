from rest_framework import serializers
from urllib.parse import urlparse, parse_qs, unquote
from .models import AffiliateProduct


def fix_image_url(raw_url: str) -> str:
    """
    Awin's image CDN (productserve.com / images2.productserve.com) wraps
    the real image URL inside a proxy like:
        https://images2.productserve.com/?w=200&h=200&...&url=ssl%3Acdn.example.com%2Fimage.jpg

    The `url=ssl%3A` part decodes to `url=ssl:` which is not a valid URL.
    The real image is at `https://<everything after ssl%3A or ssl:>`.

    This function:
    1. Detects productserve proxy URLs
    2. Extracts and fixes the inner image URL → https://...
    3. Returns it directly so the app can load it without hitting the proxy

    For all other URLs it returns them unchanged.
    """
    if not raw_url:
        return raw_url

    # Only process productserve proxy URLs
    if 'productserve.com' not in raw_url:
        return raw_url

    try:
        parsed = urlparse(raw_url)
        params = parse_qs(parsed.query)
        inner = params.get('url', [None])[0]

        if not inner:
            return raw_url

        # Decode percent-encoding: ssl%3Acdn.example.com → ssl:cdn.example.com
        inner_decoded = unquote(inner)

        # Replace the non-standard `ssl:` prefix with `https://`
        if inner_decoded.startswith('ssl://'):
            inner_decoded = 'https://' + inner_decoded[6:]
        elif inner_decoded.startswith('ssl:'):
            inner_decoded = 'https://' + inner_decoded[4:]

        # Make sure it starts with https
        if inner_decoded.startswith('https://') or inner_decoded.startswith('http://'):
            return inner_decoded

    except Exception:
        pass

    return raw_url


class AffiliateProductListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for the newsfeed list view.
    Omits heavy fields like full description to keep responses fast.
    """
    discount_percent = serializers.ReadOnlyField()
    image_url        = serializers.SerializerMethodField()

    class Meta:
        model = AffiliateProduct
        fields = [
            'id',
            'aw_product_id',
            'name',
            'brand',
            'category',
            'price',
            'rrp_price',
            'discount_percent',
            'currency',
            'colour',
            'image_url',
            'advertiser_name',
            'source',
            'is_active',
            'created_at',
        ]
        read_only_fields = fields

    def get_image_url(self, obj):
        return fix_image_url(obj.image_url)


class AffiliateProductDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for the product detail view.
    Includes description and the affiliate tracking link.
    affiliate_url is the correct deep link that lands on the specific
    product page (not just the merchant homepage).
    """
    discount_percent = serializers.ReadOnlyField()
    affiliate_url    = serializers.SerializerMethodField()
    image_url        = serializers.SerializerMethodField()

    class Meta:
        model = AffiliateProduct
        fields = [
            'id',
            'aw_product_id',
            'name',
            'brand',
            'category',
            'description',
            'price',
            'rrp_price',
            'discount_percent',
            'currency',
            'colour',
            'image_url',
            'affiliate_url',         # use THIS for the 'Buy' button — deep links to product
            'merchant_deep_link',    # direct brand URL (no tracking, fallback)
            'advertiser_name',
            'source',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_image_url(self, obj):
        return fix_image_url(obj.image_url)

    def get_affiliate_url(self, obj):
        from .views import build_affiliate_url
        return build_affiliate_url(obj)
