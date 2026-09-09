from django.urls import path
from .views import (
    TodayOutfitCreateView,
    MyOutfitsListView,
    PublicNewsfeedView,
    FollowingNewsfeedView,
    OutfitLikeToggleView,
    UserFollowToggleView,
    UserFollowersListView,
    UserFollowingListView,
    DirectMessageSendView,
    DirectMessageConversationView,
)

app_name = 'social'

urlpatterns = [
    # Outfit posts & feeds
    path('outfits/', TodayOutfitCreateView.as_view(), name='outfit-create'),
    path('my-outfits/', MyOutfitsListView.as_view(), name='my-outfits'),
    path('feed/', PublicNewsfeedView.as_view(), name='public-feed'),
    path('feed/following/', FollowingNewsfeedView.as_view(), name='following-feed'),
    path('outfits/<int:pk>/like/', OutfitLikeToggleView.as_view(), name='outfit-like'),

    # Follow / Unfollow system
    path('users/<uuid:user_id>/follow/', UserFollowToggleView.as_view(), name='user-follow'),
    path('users/<uuid:user_id>/followers/', UserFollowersListView.as_view(), name='user-followers'),
    path('users/<uuid:user_id>/following/', UserFollowingListView.as_view(), name='user-following'),

    # Direct Messaging
    path('messages/', DirectMessageSendView.as_view(), name='message-send'),
    path('messages/<uuid:user_id>/', DirectMessageConversationView.as_view(), name='message-conversation'),
]
