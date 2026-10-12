import logging
from datetime import timedelta
from typing import Dict, Any
from django.utils import timezone
from django.conf import settings
from closet.models import ClosetItem

logger = logging.getLogger(__name__)


def get_wardrobe_analytics(user, items) -> Dict[str, Any]:
    """
    Calculates digital wardrobe health, rotation metrics, ghost pieces, and environmental impact.

    Optimized:
    - If items is a queryset, uses .only() to avoid loading unneeded large blobs into memory.
    """
    if hasattr(items, 'only'):
        items = items.only(
            'id', 'user_id', 'name', 'category', 'color', 'brand',
            'price', 'times_worn', 'last_worn_at'
        )

    items_list = list(items) if not isinstance(items, list) else items
    total_items = len(items_list)
    now = timezone.now()
    ghost_days = getattr(settings, 'MYC_GHOST_DAYS', 30)
    ghost_cutoff = now - timedelta(days=ghost_days)

    if total_items == 0:
        return {
            'total_pieces': 0,
            'active_pieces': 0,
            'ghost_pieces': 0,
            'utilization_rate': 0.0,
            'status': {
                'grade': 'N/A',
                'title': 'Empty Closet',
                'badge': 'Starting Out',
                'feedback': 'Your wardrobe is currently empty. Add clothes to start tracking rotation, sustainability, and efficiency.'
            },
            'impact': {
                'wasted_carbon_kg': 0.0,
                'wasted_investment_cost': 0.0,
                'space_waste_percentage': 0.0,
                'co2_saved_kg': 0.0,
                'summary': 'Your wardrobe is currently empty. Add clothes to start tracking environmental impact and cost efficiency.'
            },
            'ghost_items': [],
            'ghost_items_qs': items if hasattr(items, 'filter') else ClosetItem.objects.none(),
            'items_list': []
        }

    ghost_items = [
        it for it in items_list
        if it.times_worn == 0 or it.last_worn_at is None or it.last_worn_at < ghost_cutoff
    ]
    ghost_count = len(ghost_items)
    active_count = max(0, total_items - ghost_count)

    utilization_rate = (active_count / total_items * 100)

    if utilization_rate >= 85:
        grade = "A+"
        title = "Conscious Curator"
        badge = "A+ Conscious Curator"
        feedback = "Masterclass in wardrobe rotation! Zero waste, maximum style efficiency."
    elif utilization_rate >= 70:
        grade = "A"
        title = "Sustainable Trendsetter"
        badge = "A Sustainable Trendsetter"
        feedback = "High efficiency wardrobe. Your pieces are in consistent, healthy rotation."
    elif utilization_rate >= 55:
        grade = "B+"
        title = "Mindful Minimalist"
        badge = "B+ Mindful Minimalist"
        feedback = "Solid active rotation on core pieces, but several ghost items need styling attention."
    elif utilization_rate >= 40:
        grade = "B"
        title = "Active Balancer"
        badge = "B Active Balancer"
        feedback = "Balanced rotation, but approximately half your closet is sitting idle."
    elif utilization_rate >= 25:
        grade = "C+"
        title = "Closet in Transition"
        badge = "C+ Closet in Transition"
        feedback = "Multiple dormant pieces taking up storage space. Consider restyling or clearing."
    else:
        grade = "C"
        title = "Ghost Heavy"
        badge = "C Ghost Heavy"
        feedback = "Majority of wardrobe is unworn. High dormant carbon and unused investment."

    wasted_carbon_kg = round(ghost_count * 12.5, 2)
    wasted_investment = float(sum((it.price or 0.0) for it in ghost_items))
    space_waste_pct = round((ghost_count / total_items * 100), 1)
    co2_saved = round(sum(max(0, it.times_worn - 1) for it in items_list) * 0.85, 2)

    return {
        'total_pieces': total_items,
        'active_pieces': active_count,
        'ghost_pieces': ghost_count,
        'utilization_rate': round(utilization_rate, 1),
        'status': {
            'grade': grade,
            'title': title,
            'badge': badge,
            'feedback': feedback,
        },
        'impact': {
            'wasted_carbon_kg': wasted_carbon_kg,
            'wasted_investment_cost': wasted_investment,
            'space_waste_percentage': space_waste_pct,
            'co2_saved_kg': co2_saved,
            'summary': "Wearing your clothes 50 times reduces their carbon footprint by 400% compared to average use."
        },
        'ghost_items': ghost_items,
        'ghost_items_qs': items.filter(id__in=[it.id for it in ghost_items]) if hasattr(items, 'filter') else ghost_items,
        'items_list': items_list
    }
