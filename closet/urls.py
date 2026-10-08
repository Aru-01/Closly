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
    path('clothes/ai-scan/<uuid:pk>/', ClosetAIScanPollView.as_view(), name='clothes-ai-scan-poll'),

    # FitCheck Async AI Processing & Polling (Spec §1.1, §7.2)
    path('fit-checks/', FitCheckCreateView.as_view(), name='fit-check-create'),
    path('fit-checks/<uuid:pk>/', FitCheckDetailView.as_view(), name='fit-check-detail'),

    # GDPR Art. 7 Consent Management (Spec §5.5, C-03)
    path('consent/', ConsentRecordView.as_view(), name='closet-consent'),

    # AI Usage & Cost Visibility (Spec §3.1, C-05)
    path('costs/', LLMCostLogListView.as_view(), name='closet-costs'),

    # Audit, score & smart AI camera scanning (P-05: async by default with polling)
    path('audit/', ClosetAuditView.as_view(), name='closet-audit'),
    path('score/', ClosetScoreDashboardView.as_view(), name='closet-score'),
    path('ai-scan/', ClosetAIScanView.as_view(), name='closet-ai-scan'),
    path('ai-scan/<uuid:pk>/', ClosetAIScanPollView.as_view(), name='closet-ai-scan-poll'),
]
