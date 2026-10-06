from django.contrib import admin
from django.db.models import Count
from unfold.admin import ModelAdmin
from .models import (
    AffiliateProduct,
    ProductClick,
    ProductFavorite,
    Brand,
    CatalogSyncRun,
    FeedAttributeMapping,
    Event,
    FeedImpressionsDaily,
    Conversion,
)


@admin.register(Brand)
class BrandAdmin(ModelAdmin):
    list_display = ('name', 'slug', 'kind', 'tier', 'status', 'currency', 'commission_pct', 'products_count', 'last_sync_at')
    list_filter = ('kind', 'tier', 'status', 'currency')
    search_fields = ('name', 'slug', 'external_id')
    readonly_fields = ('created_at', 'updated_at')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _products_count=Count('products', distinct=True)
        )

    def products_count(self, obj):
        val = getattr(obj, '_products_count', None)
        return val if val is not None else obj.products.count()
    products_count.short_description = 'Products'
    products_count.admin_order_field = '_products_count'


@admin.register(AffiliateProduct)
class AffiliateProductAdmin(ModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'brand', 'gender', 'category_norm', 'price', 'currency', 'clicks_count', 'favorites_count', 'in_stock', 'is_active', 'updated_at')
    list_filter = ('is_active', 'in_stock', 'gender', 'currency', 'source')
    search_fields = ('name', 'brand', 'aw_product_id', 'description')
    readonly_fields = ('created_at', 'updated_at', 'first_seen_at', 'last_seen_at', 'content_hash', 'cdn_image_url', 'image_hash', 'image_replicated_at')
    actions = ['activate_products', 'deactivate_products']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _clicks_count=Count('clicks', distinct=True),
            _favorites_count=Count('favorites', distinct=True),
        )

    def clicks_count(self, obj):
        val = getattr(obj, '_clicks_count', None)
        return val if val is not None else obj.clicks.count()
    clicks_count.short_description = 'Clicks'
    clicks_count.admin_order_field = '_clicks_count'

    def favorites_count(self, obj):
        val = getattr(obj, '_favorites_count', None)
        return val if val is not None else obj.favorites.count()
    favorites_count.short_description = 'Loves'
    favorites_count.admin_order_field = '_favorites_count'

    def activate_products(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, "Selected products activated successfully.")
    activate_products.short_description = "Activate selected products"

    def deactivate_products(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, "Selected products deactivated successfully.")
    deactivate_products.short_description = "Deactivate selected products"


@admin.register(ProductClick)
class ProductClickAdmin(ModelAdmin):
    list_select_related = ('product', 'user')
    show_full_result_count = False
    list_display = ('click_ref', 'product', 'user', 'surface', 'clicked_at')
    list_filter = ('surface', 'clicked_at')
    search_fields = ('click_ref', 'product__name', 'product__brand', 'user__email', 'session_id')
    readonly_fields = ('click_ref', 'clicked_at')


@admin.register(ProductFavorite)
class ProductFavoriteAdmin(ModelAdmin):
    list_select_related = ('product', 'user')
    show_full_result_count = False
    list_display = ('product', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name', 'product__brand', 'user__email', 'user__name')
    readonly_fields = ('created_at',)


@admin.register(CatalogSyncRun)
class CatalogSyncRunAdmin(ModelAdmin):
    list_display = ('feed_id', 'source', 'status', 'started_at', 'rows_seen', 'rows_new', 'rows_changed', 'rows_unchanged', 'rows_deactivated', 'error_count')
    list_filter = ('status', 'source')
    search_fields = ('feed_id', 'notes')
    readonly_fields = ('started_at', 'finished_at')


@admin.register(FeedAttributeMapping)
class FeedAttributeMappingAdmin(ModelAdmin):
    list_display = ('source', 'field', 'raw_value', 'normalized_value', 'created_at')
    list_filter = ('source', 'field')
    search_fields = ('raw_value', 'normalized_value')


@admin.register(Event)
class EventAdmin(ModelAdmin):
    list_select_related = ('user', 'product')
    list_display = ('user', 'event_type', 'event_class', 'product', 'source', 'feed_page', 'dwell_ms', 'berlin_day', 'created_at')
    list_filter = ('event_type', 'event_class', 'source', 'berlin_day')
    search_fields = ('user__email', 'product__name', 'product__brand')
    readonly_fields = ('created_at',)


@admin.register(FeedImpressionsDaily)
class FeedImpressionsDailyAdmin(ModelAdmin):
    list_select_related = ('product',)
    list_display = ('berlin_day', 'product', 'brand_name', 'impressions_count', 'clicks_count', 'saves_count', 'likes_count', 'skips_count')
    list_filter = ('berlin_day',)
    search_fields = ('brand_name', 'product__name')


@admin.register(Conversion)
class ConversionAdmin(ModelAdmin):
    list_select_related = ('user', 'product', 'brand', 'click')
    list_display = (
        'conversion_id', 'source', 'status', 'sale_amount', 'commission_amount',
        'currency', 'click_ref', 'user', 'product', 'brand', 'order_reference', 'transaction_date', 'created_at'
    )
    list_filter = ('source', 'status', 'currency', 'reward_claimed')
    search_fields = ('conversion_id', 'order_reference', 'advertiser_id', 'user__email', 'product__name')
    readonly_fields = ('created_at', 'updated_at')
