from django.contrib import admin
from .models import ClosetItem

@admin.register(ClosetItem)
class ClosetItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'category', 'brand', 'color', 'size', 'price', 'times_worn', 'per_wear_cost', 'created_at')
    list_filter = ('category', 'color', 'brand', 'created_at')
    search_fields = ('name', 'user__email', 'brand', 'color')
    readonly_fields = ('created_at', 'updated_at', 'per_wear_cost')
