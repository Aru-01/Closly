"""
Closly Luxury Admin Dashboard Metrics & Callbacks
Provides executive analytics, pending deletion counts, and KPI metrics.
"""

from django.db.models import Sum
from users.models import User, AccountDeletionRequest
from closet.models import ClosetItem
from social.models import TodayOutfit, Story


def pending_deletions_badge(request):
    """Returns the count of pending account deletion requests for the sidebar badge."""
    if not request:
        return None
    if not hasattr(request, '_cached_pending_deletions_count'):
        try:
            request._cached_pending_deletions_count = AccountDeletionRequest.objects.filter(status='pending').count()
        except Exception:
            request._cached_pending_deletions_count = 0
    count = request._cached_pending_deletions_count
    return str(count) if count > 0 else None


def dashboard_callback(request, context):
    """
    Supplements Unfold Admin index context with real-time KPI metrics,
    wardrobe valuation, and urgent deletion request alerts.
    """
    try:
        from django.db.models import Count, Q, Sum
        user_stats = User.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True))
        )
        total_users = user_stats.get('total') or 0
        active_users = user_stats.get('active') or 0

        closet_stats = ClosetItem.objects.aggregate(
            total=Count('id'),
            valuation=Sum('price')
        )
        total_closet_items = closet_stats.get('total') or 0
        wardrobe_valuation = closet_stats.get('valuation') or 0.0

        total_outfits = TodayOutfit.objects.count()
        total_stories = Story.objects.count()

        # Re-use cached pending deletion count if badge already ran, or cache it
        if request and hasattr(request, '_cached_pending_deletions_count'):
            pending_deletions_count = request._cached_pending_deletions_count
        else:
            pending_deletions_count = AccountDeletionRequest.objects.filter(status='pending').count()
            if request:
                request._cached_pending_deletions_count = pending_deletions_count

        # Recent pending deletion requests preview (up to 5)
        recent_pending_list = []
        if pending_deletions_count > 0:
            pending_deletions = list(
                AccountDeletionRequest.objects.filter(status='pending')
                .select_related('user')
                .order_by('-created_at')[:5]
            )
            # Batch fetch closet item counts to avoid N+1 queries in dashboard loop
            user_ids = [req.user_id for req in pending_deletions if req.user_id]
            missing_emails = [req.email for req in pending_deletions if not req.user_id and req.email]
            email_to_id = {}
            if missing_emails:
                email_to_id = dict(User.objects.filter(email__in=missing_emails).values_list('email', 'id'))

            all_target_user_ids = set(user_ids) | set(email_to_id.values())
            items_count_map = {}
            if all_target_user_ids:
                items_count_map = dict(
                    ClosetItem.objects.filter(user_id__in=all_target_user_ids)
                    .values('user_id')
                    .annotate(c=Count('id'))
                    .values_list('user_id', 'c')
                )

            for req in pending_deletions:
                target_user_id = req.user_id or email_to_id.get(req.email)
                user_items_count = items_count_map.get(target_user_id, 0) if target_user_id else 0
                recent_pending_list.append({
                    'id': req.id,
                    'email': req.email,
                    'name': req.name,
                    'reason': req.reason or 'User initiated deletion',
                    'details': req.details,
                    'created_at': req.created_at,
                    'items_count': user_items_count,
                })

        context.update({
            'kpi_metrics': {
                'total_users': total_users,
                'active_users': active_users,
                'pending_deletions_count': pending_deletions_count,
                'total_closet_items': total_closet_items,
                'wardrobe_valuation': f"${wardrobe_valuation:,.2f}",
                'total_outfits': total_outfits,
                'total_stories': total_stories,
            },
            'recent_pending_deletions': recent_pending_list,
        })
    except Exception as e:
        context.update({
            'kpi_metrics': {
                'total_users': 0,
                'active_users': 0,
                'pending_deletions_count': 0,
                'total_closet_items': 0,
                'wardrobe_valuation': "$0.00",
                'total_outfits': 0,
                'total_stories': 0,
            },
            'recent_pending_deletions': [],
            'dashboard_error': str(e)
        })

    return context
