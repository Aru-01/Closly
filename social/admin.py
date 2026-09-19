from django.contrib import admin
from .models import TodayOutfit, OutfitImage, OutfitLike, UserFollow, DirectMessage

class OutfitImageInline(admin.TabularInline):
    model = OutfitImage
    extra = 1
    max_num = 4

@admin.register(TodayOutfit)
class TodayOutfitAdmin(admin.ModelAdmin):
    list_display = ('user', 'visibility', 'caption', 'likes_count', 'created_at')
    list_filter = ('visibility', 'created_at')
    search_fields = ('user__email', 'caption')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OutfitImageInline]

@admin.register(OutfitLike)
class OutfitLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'outfit', 'created_at')

@admin.register(UserFollow)
class UserFollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'created_at')

@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'content', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__email', 'recipient__email', 'content')
