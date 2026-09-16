from django.urls import path
from .views import (
    TodayOutfitCreateView,
    MyOutfitsListView,
    PublicNewsfeedView,
    FollowingNewsfeedView,
    ExploreNewsfeedView,
    YourDayOutfitView,
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
    StoryCreateView,
    StoryFeedView,
    MyStoriesListView,
    StoryViewRecordView,
    StoryLikeToggleView,
    StoryReplyView,
    StoryViewersListView,
    StoryDeleteView,
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
    path('explore/', ExploreNewsfeedView.as_view(), name='explore-feed'),
    path('your-day/', YourDayOutfitView.as_view(), name='your-day'),
    path('outfits/<int:pk>/like/', OutfitLikeToggleView.as_view(), name='outfit-like'),

    # Self profile direct following & followers
    path('following/', MyFollowingListView.as_view(), name='my-following'),
    path('followers/', MyFollowersListView.as_view(), name='my-followers'),

    # Follow / Unfollow system & user profile visit
    path('users/<uuid:user_id>/follow/', UserFollowToggleView.as_view(), name='user-follow'),
    path('users/<uuid:user_id>/followers/', UserFollowersListView.as_view(), name='user-followers'),
    path('users/<uuid:user_id>/following/', UserFollowingListView.as_view(), name='user-following'),
    path('users/<uuid:user_id>/profile/', OtherUserProfileView.as_view(), name='user-social-profile'),

    # Stories system (24 hours)
    path('stories/', StoryCreateView.as_view(), name='story-create'),
    path('stories/feed/', StoryFeedView.as_view(), name='story-feed'),
    path('stories/my/', MyStoriesListView.as_view(), name='my-stories'),
    path('stories/<int:pk>/view/', StoryViewRecordView.as_view(), name='story-view'),
    path('stories/<int:pk>/like/', StoryLikeToggleView.as_view(), name='story-like'),
    path('stories/<int:pk>/reply/', StoryReplyView.as_view(), name='story-reply'),
    path('stories/<int:pk>/viewers/', StoryViewersListView.as_view(), name='story-viewers'),
    path('stories/<int:pk>/', StoryDeleteView.as_view(), name='story-delete'),

    # Direct Messaging & Inbox
    path('messages/', DirectMessageSendView.as_view(), name='message-send'),
    path('messages/inbox/', ConversationListView.as_view(), name='messages-inbox'),
    path('conversations/', ConversationListView.as_view(), name='conversations-list'),
    path('messages/<uuid:user_id>/', DirectMessageConversationView.as_view(), name='message-conversation'),
]
