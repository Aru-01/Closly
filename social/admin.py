from django.contrib import admin
from django.db.models import Count
from unfold.admin import ModelAdmin
from .models import (
    TodayOutfit,
    OutfitImage,
    OutfitLike,
    UserFollow,
    DirectMessage,
    Story,
    StoryView,
    StoryLike,
)

class OutfitImageInline(admin.TabularInline):
    model = OutfitImage
    extra = 1
    max_num = 4

@admin.register(TodayOutfit)
class TodayOutfitAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    autocomplete_fields = ('user', 'tagged_items')
    list_display = ('user', 'visibility', 'caption', 'likes_count', 'created_at')
    list_filter = ('visibility', 'created_at')
    search_fields = ('user__email', 'caption')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OutfitImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user').annotate(
            _likes_count=Count('likes', distinct=True)
        )

    def likes_count(self, obj):
        return getattr(obj, '_likes_count', obj.likes_count)
    likes_count.short_description = 'Likes'
    likes_count.admin_order_field = '_likes_count'

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('user', 'created_at', 'updated_at')
        return self.readonly_fields

@admin.register(Story)
class StoryAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    autocomplete_fields = ('user',)
    list_display = ('user', 'caption', 'created_at', 'expires_at', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__email', 'caption')
    readonly_fields = ('created_at', 'expires_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('user', 'created_at', 'expires_at')
        return self.readonly_fields

@admin.register(StoryView)
class StoryViewAdmin(ModelAdmin):
    list_select_related = ('story__user', 'viewer')
    show_full_result_count = False
    list_display = ('story', 'viewer', 'viewed_at')
    search_fields = ('story__user__email', 'viewer__email')

@admin.register(StoryLike)
class StoryLikeAdmin(ModelAdmin):
    list_select_related = ('story__user', 'user')
    show_full_result_count = False
    list_display = ('story', 'user', 'created_at')
    search_fields = ('story__user__email', 'user__email')

@admin.register(OutfitLike)
class OutfitLikeAdmin(ModelAdmin):
    list_select_related = ('user', 'outfit__user')
    show_full_result_count = False
    list_display = ('user', 'outfit', 'created_at')

@admin.register(UserFollow)
class UserFollowAdmin(ModelAdmin):
    list_select_related = ('follower', 'following')
    show_full_result_count = False
    list_display = ('follower', 'following', 'created_at')

@admin.register(DirectMessage)
class DirectMessageAdmin(ModelAdmin):
    list_select_related = ('sender', 'recipient', 'shared_outfit__user', 'story_reference__user')
    show_full_result_count = False
    autocomplete_fields = ('sender', 'recipient', 'shared_outfit', 'story_reference')
    list_display = ('sender', 'recipient', 'content', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__email', 'recipient__email', 'content')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'sender',
            'recipient',
            'shared_outfit__user',
            'story_reference__user'
        )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('sender', 'recipient', 'shared_outfit', 'story_reference', 'created_at')
        return ('created_at',)
