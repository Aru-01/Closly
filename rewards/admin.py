from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import UserRewardProfile, RewardPointTransaction


@admin.register(UserRewardProfile)
class UserRewardProfileAdmin(ModelAdmin):
    list_display = ('user', 'available_points', 'lifetime_points', 'current_tier', 'tier_updated_at')
    list_filter = ('current_tier',)
    search_fields = ('user__email', 'user__name')
    readonly_fields = ('tier_updated_at',)


@admin.register(RewardPointTransaction)
class RewardPointTransactionAdmin(ModelAdmin):
    list_display = ('user', 'action_type', 'points', 'created_at', 'expires_at', 'is_expired')
    list_filter = ('action_type', 'is_expired', 'created_at')
    search_fields = ('user__email', 'action_type', 'description')
    readonly_fields = ('created_at',)
