"""
Closet views package. Re-exports all view classes to maintain 100% backward compatibility.
"""

from .item_views import (
    ClosetItemListCreateView,
    ClosetItemDetailView,
    WearTodayView,
)

from .analytics_views import (
    get_wardrobe_analytics,
    ClosetScoreDashboardView,
    ClosetAuditView,
)

from .scanner_views import (
    ClosetAIScanView,
    scan_clothing_image,
)

__all__ = [
    'ClosetItemListCreateView',
    'ClosetItemDetailView',
    'WearTodayView',
    'get_wardrobe_analytics',
    'ClosetScoreDashboardView',
    'ClosetAuditView',
    'ClosetAIScanView',
    'scan_clothing_image',
]
