from rest_framework import serializers
from urllib.parse import urlparse, parse_qs, unquote
from .models import AffiliateProduct, ProductClick, Brand, Event, Conversion


def fix_image_url(raw_url: str) -> str:
    """
    Awin's image CDN (productserve.com / images2.productserve.com) wraps
    the real image URL inside a proxy like:
        https://images2.productserve.com/?w=200&h=200&...&url=ssl%3Acdn.example.com%2Fimage.jpg

    The `url=ssl%3A` part decodes to `url=ssl:` which is not a valid URL.
    The real image is at `https://<everything after ssl%3A or ssl:>`.

    This function:
    1. Detects productserve proxy URLs
    2. Extracts and fixes the inner image URL -> https://...
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

        # Decode percent-encoding: ssl%3Acdn.example.com -> ssl:cdn.example.com
        inner_decoded = unquote(inner)

        # Replace the non-standard `ssl:` prefix with `https://`
        if inner_decoded.startswith('ssl://'):
            inner_decoded = 'https://' + inner_decoded[6:]
        elif inner_decoded.startswith('ssl:'):
            inner_decoded = 'https://' + inner_decoded[4:]

        # Make sure it starts with https
        if inner_decoded.startswith('https://') or inner_decoded.startswith('http://'):
            return inner_decoded

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to fix image url: {e}")

    return raw_url


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            'id',
            'name',
            'slug',
            'kind',
            'tier',
            'status',
            'currency',
            'commission_pct',
        ]
        read_only_fields = fields


class AffiliateProductListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for the newsfeed and discovery list views.
    Omits heavy fields like full description to keep responses fast.
    """
    discount_percent = serializers.ReadOnlyField()
    image_url        = serializers.SerializerMethodField()
    is_loved         = serializers.SerializerMethodField()
    favorites_count  = serializers.SerializerMethodField()
    brand_id         = serializers.IntegerField(source='brand_ref_id', read_only=True)

    class Meta:
        model = AffiliateProduct
        fields = [
            'id',
            'aw_product_id',
            'name',
            'brand',
            'brand_id',
            'category',
            'category_norm',
            'gender',
            'price',
            'rrp_price',
            'discount_percent',
            'currency',
            'colour',
            'color_primary',
            'image_url',
            'cdn_image_url',
            'image_hash',
            'advertiser_name',
            'source',
            'in_stock',
            'is_loved',
            'favorites_count',
            'is_active',
            'created_at',
        ]
        read_only_fields = fields

    def get_image_url(self, obj):
        if obj.cdn_image_url:
            return obj.cdn_image_url
        return fix_image_url(obj.image_url)

    def get_is_loved(self, obj):
        favorite_ids = self.context.get('favorite_product_ids')
        if favorite_ids is not None:
            return obj.id in favorite_ids
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return obj.favorites.filter(user=request.user).exists()
        return False

    def get_favorites_count(self, obj):
        if hasattr(obj, '_favorites_count'):
            return obj._favorites_count
        return obj.favorites.count()


class AffiliateProductDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for the product detail view.
    Includes description and the affiliate tracking link.
    Notice: Outbound purchase clicks should go via POST /api/affiliate/products/<id>/click/
    to mint a unique click reference UUID for conversion attribution.
    """
    discount_percent = serializers.ReadOnlyField()
    affiliate_url    = serializers.SerializerMethodField()
    image_url        = serializers.SerializerMethodField()
    images           = serializers.SerializerMethodField()
    is_loved         = serializers.SerializerMethodField()
    favorites_count  = serializers.SerializerMethodField()
    clicks_count     = serializers.SerializerMethodField()
    brand_id         = serializers.IntegerField(source='brand_ref_id', read_only=True)

    class Meta:
        model = AffiliateProduct
        fields = [
            'id',
            'aw_product_id',
            'name',
            'brand',
            'brand_id',
            'category',
            'category_norm',
            'gender',
            'description',
            'price',
            'rrp_price',
            'discount_percent',
            'currency',
            'colour',
            'color_primary',
            'image_url',
            'cdn_image_url',
            'image_hash',
            'images',                # All available product images (gallery/carousel)
            'affiliate_url',         # Deep link to product (attribution routed via /click/)
            'merchant_deep_link',    # direct brand URL (no tracking, fallback)
            'advertiser_name',
            'source',
            'in_stock',
            'sizes',
            'is_loved',
            'favorites_count',
            'clicks_count',          # Total users who clicked 'Buy' on this product
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_image_url(self, obj):
        if obj.cdn_image_url:
            return obj.cdn_image_url
        return fix_image_url(obj.image_url)

    def get_images(self, obj):
        primary = obj.cdn_image_url or fix_image_url(obj.image_url)
        raw_extra = getattr(obj, 'additional_image_urls', []) or []
        extra = [fix_image_url(u) for u in raw_extra if u and isinstance(u, str)]
        res = []
        if primary:
            res.append(primary)
        for u in extra:
            if u not in res:
                res.append(u)
        return res

    def get_affiliate_url(self, obj):
        from .views.product_views import build_affiliate_url
        return build_affiliate_url(obj)

    def get_is_loved(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return obj.favorites.filter(user=request.user).exists()
        return False

    def get_favorites_count(self, obj):
        if hasattr(obj, '_favorites_count'):
            return obj._favorites_count
        return obj.favorites.count()

    def get_clicks_count(self, obj):
        if hasattr(obj, '_clicks_count'):
            return obj._clicks_count
        return obj.clicks.count()


class EventItemSerializer(serializers.Serializer):
    """
    Serializer for individual behavioral events in batch submission.
    """
    event_type = serializers.ChoiceField(choices=Event.TYPE_CHOICES)
    product_id = serializers.IntegerField()
    source = serializers.CharField(max_length=50, required=False, default='for_you')
    feed_page = serializers.IntegerField(required=False, allow_null=True)
    dwell_ms = serializers.IntegerField(required=False, allow_null=True)
    client_ts = serializers.DateTimeField(required=False, allow_null=True)


class EventBatchSerializer(serializers.Serializer):
    """
    Serializer for batch event ingestion (up to 200 events).
    """
    events = serializers.ListField(
        child=EventItemSerializer(),
        max_length=200,
        allow_empty=False,
    )


class ConversionSerializer(serializers.ModelSerializer):
    """
    Serializer for Conversion & Transaction Attribution records (Audit CF-30).
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)

    class Meta:
        model = Conversion
        fields = [
            'id',
            'conversion_id',
            'source',
            'click_ref',
            'user',
            'product',
            'product_name',
            'brand',
            'brand_name',
            'advertiser_id',
            'order_reference',
            'status',
            'sale_amount',
            'commission_amount',
            'currency',
            'transaction_date',
            'validation_date',
            'reward_claimed',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
