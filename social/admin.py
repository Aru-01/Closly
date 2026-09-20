from django.contrib import admin
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
    list_display = ('user', 'visibility', 'caption', 'likes_count', 'created_at')
    list_filter = ('visibility', 'created_at')
    search_fields = ('user__email', 'caption')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OutfitImageInline]

@admin.register(Story)
class StoryAdmin(ModelAdmin):
    list_display = ('user', 'caption', 'created_at', 'expires_at', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__email', 'caption')
    readonly_fields = ('created_at', 'expires_at')

@admin.register(StoryView)
class StoryViewAdmin(ModelAdmin):
    list_display = ('story', 'viewer', 'viewed_at')
    search_fields = ('story__user__email', 'viewer__email')

@admin.register(StoryLike)
class StoryLikeAdmin(ModelAdmin):
    list_display = ('story', 'user', 'created_at')
    search_fields = ('story__user__email', 'user__email')

@admin.register(OutfitLike)
class OutfitLikeAdmin(ModelAdmin):
    list_display = ('user', 'outfit', 'created_at')

@admin.register(UserFollow)
class UserFollowAdmin(ModelAdmin):
    list_display = ('follower', 'following', 'created_at')

@admin.register(DirectMessage)
class DirectMessageAdmin(ModelAdmin):
    list_display = ('sender', 'recipient', 'content', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__email', 'recipient__email', 'content')
