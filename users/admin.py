from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import redirect
from django.db.models import Sum, Count, Q
from unfold.admin import ModelAdmin
from unfold.decorators import display

from closet.models import ClosetItem
from social.models import TodayOutfit, Story
from .models import (
    User,
    UserLoginHistory,
    AccountDeletionRequest,
    ProfileDataDeletionRequest,
    UserPreference,
)
from .utils import purge_and_anonymize_user


@admin.register(UserPreference)
class UserPreferenceAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    autocomplete_fields = ('user',)
    list_display = [
        'user',
        'body_type',
        'body_size',
        'color_palette',
        'onboarding_completed',
        'created_at',
        'updated_at',
    ]
    list_filter = [
        'onboarding_completed',
        'body_type',
        'body_size',
        'color_palette',
        'created_at',
    ]
    search_fields = [
        'user__email',
        'user__name',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
    ]
    ordering = ['-created_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('user', 'created_at', 'updated_at')
        return self.readonly_fields


@admin.register(ProfileDataDeletionRequest)
class ProfileDataDeletionRequestAdmin(ModelAdmin):
    list_select_related = ('user',)
    show_full_result_count = False
    list_display = ('email', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('email',)
    readonly_fields = ('email', 'user', 'created_at', 'updated_at', 'verification_token')


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(ModelAdmin):
    change_form_template = "admin/users/accountdeletionrequest/change_form.html"
    list_select_related = ('user',)
    show_full_result_count = False
    list_display = (
        'id',
        'user_display',
        'reason_display',
        'wardrobe_items_count',
        'status_badge',
        'created_at',
        'action_buttons',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'email', 'reason', 'details')
    readonly_fields = ('user', 'created_at', 'updated_at', 'verification_token')
    actions = ['accept_and_purge_accounts', 'reject_deletion_requests']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user').annotate(
            _closet_items_count=Count('user__closet_items', distinct=True)
        )

    def get_object(self, request, object_id, from_field=None):
        cache_attr = f'_cached_del_obj_{object_id}'
        if hasattr(request, cache_attr):
            return getattr(request, cache_attr)
        obj = super().get_object(request, object_id, from_field)
        setattr(request, cache_attr, obj)
        return obj

    fieldsets = (
        ("Request Status & Feedback", {
            "fields": ("status", "reason", "details", "name", "email", "user"),
        }),
        ("Audit & Token Security", {
            "fields": ("verification_token", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @display(description="User / Applicant", header=True)
    def user_display(self, obj):
        return [obj.name or "User", obj.email]

    @display(description="Reason")
    def reason_display(self, obj):
        reason_text = obj.reason or "Account deletion requested"
        if len(reason_text) > 35:
            return reason_text[:32] + "..."
        return reason_text

    @display(description="Wardrobe Pieces")
    def wardrobe_items_count(self, obj):
        if hasattr(obj, '_closet_items_count'):
            return f"{obj._closet_items_count} pieces"
        if not obj.user:
            return "0 pieces"
        count = ClosetItem.objects.filter(user=obj.user).count()
        return f"{count} pieces"

    @display(
        description="Status",
        label={
            "pending": "warning",
            "completed": "success",
            "rejected": "danger",
        }
    )
    def status_badge(self, obj):
        return obj.status

    def action_buttons(self, obj):
        if obj.status == 'pending':
            url = reverse('admin:accept_account_deletion', args=[obj.pk])
            return format_html(
                '<a class="button" style="background:#dc2626;color:#ffffff;font-weight:600;padding:5px 12px;border-radius:6px;text-decoration:none;font-size:12px;" href="{}" onclick="return confirm(\'Permanently purge all data for {}?\');">Purge & Erase</a>',
                url, obj.email
            )
        elif obj.status == 'completed':
            return format_html('<span style="color:#16a34a;font-weight:600;font-size:12px;">✓ Completed</span>')
        return format_html('<span style="color:#64748b;font-size:12px;">{}</span>', obj.get_status_display())
    action_buttons.short_description = 'Actions'

    @admin.action(description="Accept & Purge Selected User Accounts")
    def accept_and_purge_accounts(self, request, queryset):
        purged_count = 0
        for req in queryset:
            if req.status != 'completed' and req.user:
                purge_and_anonymize_user(req.user)
                req.status = 'completed'
                req.save()
                purged_count += 1
            elif req.status != 'completed':
                req.status = 'completed'
                req.save()
        self.message_user(
            request,
            f"Successfully processed {purged_count} account deletion(s). Confirmation emails dispatched and private data wiped.",
            messages.SUCCESS
        )

    @admin.action(description="Reject Selected Deletion Requests")
    def reject_deletion_requests(self, request, queryset):
        count = queryset.filter(status='pending').update(status='rejected')
        self.message_user(
            request,
            f"Marked {count} deletion request(s) as rejected.",
            messages.WARNING
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:req_id>/accept-purge/',
                self.admin_site.admin_view(self.process_single_approval),
                name='accept_account_deletion'
            ),
        ]
        return custom_urls + urls

    def process_single_approval(self, request, req_id):
        req = self.get_object(request, str(req_id))
        if req:
            if req.user:
                purge_and_anonymize_user(req.user)
            req.status = 'completed'
            req.save()
            self.message_user(
                request,
                f"Account deletion for {req.email} accepted. Data export email sent and private data wiped.",
                messages.SUCCESS
            )
        return redirect('admin:users_accountdeletionrequest_changelist')

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """
        Inject live nested dossier data about the target user account,
        their digital wardrobe footprint, and social activity to present to admin.
        """
        extra_context = extra_context or {}
        if object_id:
            obj = self.get_object(request, object_id)
            if obj:
                u = obj.user or User.objects.filter(email=obj.email).first()
                if u:
                    # If obj.user wasn't linked yet, link it now
                    if not obj.user:
                        obj.user = u
                        obj.save(update_fields=['user'])

                    items_qs = ClosetItem.objects.filter(user=u)
                    # Consolidate 7 queries into 1 single aggregate query
                    stats = items_qs.aggregate(
                        total_count=Count('id'),
                        total_valuation=Sum('price'),
                        tops=Count('id', filter=Q(category='top')),
                        bottoms=Count('id', filter=Q(category='bottom')),
                        outerwear=Count('id', filter=Q(category='dresses_outerwear')),
                        shoes=Count('id', filter=Q(category='shoes')),
                        accessories=Count('id', filter=Q(category__in=['accessories', 'other'])),
                    )
                    total_items = stats['total_count'] or 0
                    total_val = stats['total_valuation'] or 0.0

                    tops = stats['tops'] or 0
                    bottoms = stats['bottoms'] or 0
                    outerwear = stats['outerwear'] or 0
                    shoes = stats['shoes'] or 0
                    accessories = stats['accessories'] or 0

                    preview_items = list(items_qs[:10])

                    outfits_count = TodayOutfit.objects.filter(user=u).count()
                    stories_count = Story.objects.filter(user=u).count()

                    followers_count = getattr(u, 'followers', None).count() if hasattr(u, 'followers') else 0
                    following_count = getattr(u, 'following', None).count() if hasattr(u, 'following') else 0

                    from rewards.models import UserRewardProfile
                    closet_points = (
                        UserRewardProfile.objects.filter(user=u)
                        .values_list('available_points', flat=True)
                        .first() or 0
                    )

                    extra_context.update({
                        'user_info': {
                            'id': u.id,
                            'name': u.name,
                            'email': u.email,
                            'phone': getattr(u, 'phone', None),
                            'auth_provider': getattr(u, 'auth_provider', 'email'),
                            'is_email_verified': u.is_email_verified,
                            'date_joined': u.date_joined,
                            'last_login': u.last_login,
                        },
                        'wardrobe_stats': {
                            'total_count': total_items,
                            'total_valuation': total_val,
                            'tops_count': tops,
                            'bottoms_count': bottoms,
                            'outerwear_count': outerwear,
                            'shoes_count': shoes,
                            'accessories_count': accessories,
                            'items': preview_items,
                        },
                        'social_stats': {
                            'outfits_count': outfits_count,
                            'stories_count': stories_count,
                            'followers_count': followers_count,
                            'following_count': following_count,
                            'closet_points': closet_points,
                        }
                    })
                else:
                    # Provide clean default stats so UI never renders broken/empty states
                    extra_context.update({
                        'user_info': None,
                        'wardrobe_stats': {
                            'total_count': 0,
                            'total_valuation': 0.0,
                            'tops_count': 0,
                            'bottoms_count': 0,
                            'outerwear_count': 0,
                            'shoes_count': 0,
                            'accessories_count': 0,
                            'items': [],
                        },
                        'social_stats': {
                            'outfits_count': 0,
                            'stories_count': 0,
                            'followers_count': 0,
                            'following_count': 0,
                            'closet_points': 0,
                        }
                    })
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)




@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User Admin with enhanced display and filters
    """
    show_full_result_count = False

    def get_object(self, request, object_id, from_field=None):
        if request and getattr(request, 'user', None) and request.user.is_authenticated and str(request.user.pk) == str(object_id):
            return request.user
        cache_attr = f'_cached_user_obj_{object_id}'
        if hasattr(request, cache_attr):
            return getattr(request, cache_attr)
        obj = super().get_object(request, object_id, from_field)
        setattr(request, cache_attr, obj)
        return obj

    # Display fields in list view
    list_display = [
        'email',
        'name',
        'auth_provider',
        'is_email_verified',
        'is_active',
        'is_staff',
        'date_joined',
        'last_login',
    ]
    
    # Filters in sidebar
    list_filter = [
        'is_active',
        'is_staff',
        'is_superuser',
        'is_email_verified',
        'auth_provider',
        'date_joined',
        'last_login',
    ]
    
    # Search fields
    search_fields = ['email', 'name', 'firebase_uid']
    
    # Ordering
    ordering = ['-date_joined']
    
    # Fields to display in detail view
    fieldsets = (
        (None, {
            'fields': ('email', 'password')
        }),
        (_('Personal Info'), {
            'fields': ('name', 'date_of_birth', 'profile_picture')
        }),
        (_('Authentication'), {
            'fields': (
                'auth_provider',
                'firebase_uid',
                'is_email_verified',
            )
        }),
        (_('Permissions'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            ),
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined', 'updated_at')
        }),
        (_('OTP'), {
            'fields': (
                'otp',
                'otp_created_at',
                'password_reset_verified',
            ),
            'classes': ('collapse',),  # Collapsible section
        }),
    )
    
    # Fields to display when adding a new user
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'name',
                'date_of_birth',
                'password1',
                'password2',
                'is_active',
                'is_staff',
            ),
        }),
    )
    
    # Read-only fields
    readonly_fields = [
        'date_joined',
        'last_login',
        'updated_at',
        'otp_created_at',
    ]
    
    # Fields that can be filtered by date
    date_hierarchy = 'date_joined'
    
    # Enable bulk actions
    actions = ['activate_users', 'deactivate_users', 'verify_emails']
    
    def activate_users(self, request, queryset):
        """Bulk action to activate users"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated successfully.')
    activate_users.short_description = 'Activate selected users'
    
    def deactivate_users(self, request, queryset):
        """Bulk action to deactivate users"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated successfully.')
    deactivate_users.short_description = 'Deactivate selected users'
    
    def verify_emails(self, request, queryset):
        """Bulk action to verify user emails"""
        updated = queryset.update(is_email_verified=True)
        self.message_user(request, f'{updated} user email(s) verified successfully.')
    verify_emails.short_description = 'Verify emails of selected users'


@admin.register(UserLoginHistory)
class UserLoginHistoryAdmin(admin.ModelAdmin):
    """
    Admin interface for User Login History
    """
    list_select_related = ('user',)
    show_full_result_count = False

    # Display fields in list view
    list_display = [
        'user',
        'auth_method',
        'login_time',
        'ip_address',
        'get_user_agent_preview',
    ]
    
    # Filters in sidebar
    list_filter = [
        'auth_method',
        'login_time',
    ]
    
    # Search fields
    search_fields = [
        'user__email',
        'user__name',
        'ip_address',
    ]
    
    # Ordering
    ordering = ['-login_time']
    
    # Read-only fields (login history should not be editable)
    readonly_fields = [
        'user',
        'login_time',
        'ip_address',
        'user_agent',
        'auth_method',
    ]
    
    # Fields to display in detail view
    fields = [
        'user',
        'auth_method',
        'login_time',
        'ip_address',
        'user_agent',
    ]
    
    # Date hierarchy
    date_hierarchy = 'login_time'
    
    # Disable add and change permissions (only view)
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def get_user_agent_preview(self, obj):
        """Show preview of user agent (first 50 characters)"""
        if obj.user_agent:
            return obj.user_agent[:50] + '...' if len(obj.user_agent) > 50 else obj.user_agent
        return '-'
    get_user_agent_preview.short_description = 'User Agent'


# Customize admin site header and title
admin.site.site_header = 'User Authentication Admin'
admin.site.site_title = 'Admin Portal'
admin.site.index_title = 'Welcome to User Authentication Administration'