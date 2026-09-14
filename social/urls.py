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
    MyFollowersListView,
    MyFollowingListView,
    OtherUserProfileView,
    DirectMessageSendView,
    DirectMessageConversationView,
    ConversationListView,
    LikedOutfitsListView,
    OutfitCalendarView,
)

app_name = 'social'

urlpatterns = [
    # Outfit posts, feeds, and calendar
    path('outfits/', TodayOutfitCreateView.as_view(), name='outfit-create'),
    path('my-outfits/', MyOutfitsListView.as_view(), name='my-outfits'),
    path('outfits/liked/', LikedOutfitsListView.as_view(), name='outfits-liked'),
    path('outfits/calendar/', OutfitCalendarView.as_view(), name='outfits-calendar'),
    path('feed/', PublicNewsfeedView.as_view(), name='public-feed'),
    path('feed/following/', FollowingNewsfeedView.as_view(), name='following-feed'),
    path('outfits/<int:pk>/like/', OutfitLikeToggleView.as_view(), name='outfit-like'),

    # Self profile direct following & followers
    path('following/', MyFollowingListView.as_view(), name='my-following'),
    path('followers/', MyFollowersListView.as_view(), name='my-followers'),

    # Follow / Unfollow system & user profile visit
    path('users/<uuid:user_id>/follow/', UserFollowToggleView.as_view(), name='user-follow'),
    path('users/<uuid:user_id>/followers/', UserFollowersListView.as_view(), name='user-followers'),
    path('users/<uuid:user_id>/following/', UserFollowingListView.as_view(), name='user-following'),
    path('users/<uuid:user_id>/profile/', OtherUserProfileView.as_view(), name='user-social-profile'),

    # Direct Messaging & Inbox
    path('messages/', DirectMessageSendView.as_view(), name='message-send'),
    path('messages/inbox/', ConversationListView.as_view(), name='messages-inbox'),
    path('conversations/', ConversationListView.as_view(), name='conversations-list'),
    path('messages/<uuid:user_id>/', DirectMessageConversationView.as_view(), name='message-conversation'),
]
