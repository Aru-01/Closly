from django.urls import path
from .views import (
    RewardPointsSummaryView,
    RewardPointsHistoryView,
    ClaimPurchaseRewardView,
)

app_name = 'rewards'

urlpatterns = [
    path('points/', RewardPointsSummaryView.as_view(), name='points-summary'),
    path('points/history/', RewardPointsHistoryView.as_view(), name='points-history'),
    path('points/claim-purchase/', ClaimPurchaseRewardView.as_view(), name='claim-purchase'),
]
