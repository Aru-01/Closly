from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import (
    UserRewardProfile,
    RewardPointTransaction,
    LedgerAccount,
    PointAward,
    LedgerTxn,
    LedgerEntry,
    AwardStateLog,
)


@admin.register(UserRewardProfile)
class UserRewardProfileAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    autocomplete_fields = ('user',)
    list_display = ('user', 'available_points', 'lifetime_points', 'current_tier', 'tier_updated_at')
    list_filter = ('current_tier',)
    search_fields = ('user__email', 'user__name')
    readonly_fields = ('user', 'available_points', 'lifetime_points', 'current_tier', 'tier_updated_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RewardPointTransaction)
class RewardPointTransactionAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    autocomplete_fields = ('user',)
    list_display = ('user', 'action_type', 'points', 'status', 'created_at', 'expires_at', 'is_expired')
    list_filter = ('action_type', 'status', 'is_expired', 'created_at')
    search_fields = ('user__email', 'action_type', 'description', 'reference_id')
    readonly_fields = ('user', 'action_type', 'points', 'description', 'reference_id', 'status', 'expires_at', 'is_expired', 'created_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerAccount)
class LedgerAccountAdmin(ModelAdmin):
    list_display = ('kind', 'user', 'created_at')
    list_filter = ('kind',)
    search_fields = ('user__email', 'kind')
    readonly_fields = ('kind', 'user', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PointAward)
class PointAwardAdmin(ModelAdmin):
    list_display = ('id', 'user', 'award_type', 'points_current', 'points_original', 'state', 'created_at', 'expires_at')
    list_filter = ('award_type', 'state', 'created_at')
    search_fields = ('user__email', 'conversion_reference', 'click_reference')
    readonly_fields = (
        'user', 'award_type', 'points_original', 'points_current', 'state',
        'click_reference', 'conversion_reference', 'referred_user', 'outfit_id',
        'eta_available_at', 'available_at', 'expires_at', 'created_at', 'updated_at'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerTxn)
class LedgerTxnAdmin(ModelAdmin):
    list_display = ('id', 'txn_type', 'description', 'idempotency_key', 'created_at')
    list_filter = ('txn_type', 'created_at')
    search_fields = ('idempotency_key', 'description', 'conversion_reference')
    readonly_fields = ('id', 'txn_type', 'award', 'conversion_reference', 'idempotency_key', 'description', 'created_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ModelAdmin):
    list_display = ('id', 'txn', 'account', 'points', 'created_at')
    search_fields = ('txn__idempotency_key', 'account__kind', 'account__user__email')
    readonly_fields = ('txn', 'account', 'points', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AwardStateLog)
class AwardStateLogAdmin(ModelAdmin):
    list_display = ('id', 'award', 'from_state', 'to_state', 'points_delta', 'actor', 'created_at')
    list_filter = ('from_state', 'to_state', 'created_at')
    search_fields = ('award__id', 'reason', 'actor')
    readonly_fields = ('award', 'from_state', 'to_state', 'reason', 'points_delta', 'actor', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
