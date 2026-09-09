from django.contrib import admin
from .models import AffiliateProduct

@admin.register(AffiliateProduct)
class AffiliateProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'price', 'currency', 'category', 'is_active', 'updated_at')
    list_filter = ('is_active', 'brand', 'currency', 'category')
    search_fields = ('name', 'brand', 'aw_product_id', 'description')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['activate_products', 'deactivate_products']

    def activate_products(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, "Selected products activated successfully.")
    activate_products.short_description = "Activate selected products"

    def deactivate_products(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, "Selected products deactivated successfully.")
    deactivate_products.short_description = "Deactivate selected products"
