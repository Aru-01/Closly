from django.urls import path
from .views import (
    ClosetItemListCreateView,
    ClosetItemDetailView,
    WearTodayView,
    ClosetAuditView,
)

app_name = 'closet'

urlpatterns = [
    path('items/', ClosetItemListCreateView.as_view(), name='item-list-create'),
    path('items/<int:pk>/', ClosetItemDetailView.as_view(), name='item-detail'),
    path('items/<int:pk>/wear-today/', WearTodayView.as_view(), name='wear-today'),
    path('audit/', ClosetAuditView.as_view(), name='closet-audit'),
]
