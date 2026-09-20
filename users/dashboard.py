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
    try:
        count = AccountDeletionRequest.objects.filter(status='pending').count()
        return str(count) if count > 0 else None
    except Exception:
        return None


def dashboard_callback(request, context):
    """
    Supplements Unfold Admin index context with real-time KPI metrics,
    wardrobe valuation, and urgent deletion request alerts.
    """
    try:
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        pending_deletions = AccountDeletionRequest.objects.filter(status='pending').select_related('user').order_by('-created_at')
        pending_deletions_count = pending_deletions.count()

        total_closet_items = ClosetItem.objects.count()
        total_outfits = TodayOutfit.objects.count()
        total_stories = Story.objects.count()

        valuation_aggregate = ClosetItem.objects.aggregate(total_val=Sum('price'))
        wardrobe_valuation = valuation_aggregate.get('total_val') or 0.0

        # Recent pending deletion requests preview (up to 5)
        recent_pending_list = []
        for req in pending_deletions[:5]:
            target_user = req.user or User.objects.filter(email=req.email).first()
            user_items_count = ClosetItem.objects.filter(user=target_user).count() if target_user else 0
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
