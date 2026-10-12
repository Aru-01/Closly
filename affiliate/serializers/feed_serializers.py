import logging
from urllib.parse import urlparse, parse_qs, unquote
from rest_framework import serializers

from affiliate.models import AffiliateProduct, Brand

logger = logging.getLogger(__name__)


def fix_image_url(raw_url: str) -> str:
    """
    Awin's image CDN (productserve.com / images2.productserve.com) wraps
    the real image URL inside a proxy like:
        https://images2.productserve.com/?w=200&h=200&...&url=ssl%3Acdn.example.com%2Fimage.jpg

    The `url=ssl%3A` part decodes to `url=ssl:` which is not a valid URL.
    The real image is at `https://<everything after ssl%3A or ssl:>`.
    """
    if not raw_url:
        return raw_url

    if 'productserve.com' not in raw_url:
        return raw_url

    try:
        parsed = urlparse(raw_url)
        params = parse_qs(parsed.query)
        inner = params.get('url', [None])[0]

        if not inner:
            return raw_url

        inner_decoded = unquote(inner)

        if inner_decoded.startswith('ssl://'):
            inner_decoded = 'https://' + inner_decoded[6:]
        elif inner_decoded.startswith('ssl:'):
            inner_decoded = 'https://' + inner_decoded[4:]

        if inner_decoded.startswith('https://') or inner_decoded.startswith('http://'):
            return inner_decoded

    except Exception as e:
        logger.warning(f"Failed to fix image url: {e}")

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
            'images',
            'affiliate_url',
            'merchant_deep_link',
            'advertiser_name',
            'source',
            'in_stock',
            'sizes',
            'is_loved',
            'favorites_count',
            'clicks_count',
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
        from affiliate.services.catalog_services import build_affiliate_url
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
