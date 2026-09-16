from django.urls import path
from .views import (
    ClosetItemListCreateView,
    ClosetItemDetailView,
    WearTodayView,
    ClosetAuditView,
    ClosetScoreDashboardView,
    ClosetAIScanView,
)

app_name = 'closet'

urlpatterns = [
    # Wardrobe items (both 'items' and 'clothes' endpoints supported for mobile developer convenience)
    path('items/', ClosetItemListCreateView.as_view(), name='item-list-create'),
    path('items/<int:pk>/', ClosetItemDetailView.as_view(), name='item-detail'),
    path('items/<int:pk>/wear-today/', WearTodayView.as_view(), name='wear-today'),
    path('items/<int:pk>/wear/', WearTodayView.as_view(), name='wear-today-alias'),

    path('clothes/', ClosetItemListCreateView.as_view(), name='clothes-list-create'),
    path('clothes/<int:pk>/', ClosetItemDetailView.as_view(), name='clothes-detail'),
    path('clothes/<int:pk>/wear/', WearTodayView.as_view(), name='clothes-wear'),
    path('clothes/<int:pk>/wear-today/', WearTodayView.as_view(), name='clothes-wear-today'),
    path('clothes/ai-scan/', ClosetAIScanView.as_view(), name='clothes-ai-scan'),

    # Audit, score & smart AI camera scanning
    path('audit/', ClosetAuditView.as_view(), name='closet-audit'),
    path('score/', ClosetScoreDashboardView.as_view(), name='closet-score'),
    path('ai-scan/', ClosetAIScanView.as_view(), name='closet-ai-scan'),
]
