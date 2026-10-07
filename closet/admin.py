from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import ClosetItem, FitCheck


@admin.register(ClosetItem)
class ClosetItemAdmin(ModelAdmin):
    list_select_related = ('user', 'fit_check')
    show_full_result_count = False
    list_display = ('name', 'user', 'category', 'brand', 'price', 'currency', 'source', 'times_worn', 'per_wear_cost', 'created_at')
    list_filter = ('category', 'source', 'currency', 'created_at')
    search_fields = ('name', 'user__email', 'brand', 'color', 'photo_sha256')
    readonly_fields = ('created_at', 'updated_at', 'per_wear_cost', 'photo_sha256')


@admin.register(FitCheck)
class FitCheckAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    list_display = ('id', 'user', 'status', 'tagging_model', 'photo_sha256', 'created_at', 'tagged_at')
    list_filter = ('status', 'tagging_model', 'created_at')
    search_fields = ('id', 'user__email', 'photo_sha256')
    readonly_fields = ('id', 'created_at', 'tagged_at', 'photo_sha256', 'raw_tagging')

