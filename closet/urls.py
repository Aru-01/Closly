from django.urls import path
from .views import (
    ClosetItemListCreateView,
    ClosetItemDetailView,
    WearTodayView,
    ClosetAuditView,
    ClosetScoreDashboardView,
    ClosetAIScanView,
    ClosetAIScanPollView,
    FitCheckCreateView,
    FitCheckDetailView,
    ConsentRecordView,
    LLMCostLogListView,
)

app_name = 'closet'

urlpatterns = [
    # Wardrobe items (Canonical REST: /items/)
    path('items/', ClosetItemListCreateView.as_view(), name='item-list-create'),
    path('items/<int:pk>/', ClosetItemDetailView.as_view(), name='item-detail'),
    path('items/<int:pk>/wear/', WearTodayView.as_view(), name='wear-today'),

    # FitCheck Async AI Processing & Polling
    path('fit-checks/', FitCheckCreateView.as_view(), name='fit-check-create'),
    path('fit-checks/<str:pk>/', FitCheckDetailView.as_view(), name='fit-check-detail'),

    # GDPR Art. 7 Consent Management
    path('consent/', ConsentRecordView.as_view(), name='closet-consent'),

    # AI Usage & Cost Visibility
    path('costs/', LLMCostLogListView.as_view(), name='closet-costs'),

    # Wardrobe Audit, Sustainability Score & Smart AI Camera Scan
    path('audit/', ClosetAuditView.as_view(), name='closet-audit'),
    path('score/', ClosetScoreDashboardView.as_view(), name='closet-score'),
    path('ai-scan/', ClosetAIScanView.as_view(), name='closet-ai-scan'),
    path('ai-scan/<str:pk>/', ClosetAIScanPollView.as_view(), name='closet-ai-scan-poll'),
]
