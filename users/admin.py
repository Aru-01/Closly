from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, UserLoginHistory, AccountDeletionRequest, ProfileDataDeletionRequest
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.html import format_html

@admin.register(ProfileDataDeletionRequest)
class ProfileDataDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('email',)
    readonly_fields = ('email', 'user', 'created_at', 'updated_at', 'verification_token')

@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'email')
    readonly_fields = ('name', 'email', 'user', 'created_at', 'updated_at', 'verification_token')



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User Admin with enhanced display and filters
    """
    
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