from django.contrib import admin
from django.db.models import Count
from unfold.admin import ModelAdmin
from .models import AffiliateProduct, ProductClick, ProductFavorite

@admin.register(AffiliateProduct)
class AffiliateProductAdmin(ModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'brand', 'price', 'currency', 'clicks_count', 'favorites_count', 'is_active', 'updated_at')
    list_filter = ('is_active', 'brand', 'currency', 'category')
    search_fields = ('name', 'brand', 'aw_product_id', 'description')
    readonly_fields = ('created_at', 'updated_at')
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
    list_display = ('product', 'user', 'clicked_at')
    list_filter = ('clicked_at', 'product__brand')
    search_fields = ('product__name', 'product__brand', 'user__email', 'user__name')
    readonly_fields = ('clicked_at',)


@admin.register(ProductFavorite)
class ProductFavoriteAdmin(ModelAdmin):
    list_select_related = ('product', 'user')
    show_full_result_count = False
    list_display = ('product', 'user', 'created_at')
    list_filter = ('created_at', 'product__brand')
    search_fields = ('product__name', 'product__brand', 'user__email', 'user__name')
    readonly_fields = ('created_at',)

