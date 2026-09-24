from django.urls import path
from .views import (
    TodayOutfitCreateView,
    MyOutfitsListView,
    OutfitDetailView,
    OutfitLikeToggleView,
    OutfitLikersListView,
    PublicNewsfeedView,
    FollowingNewsfeedView,
    ExploreNewsfeedView,
    YourDayOutfitView,
    UserFollowToggleView,
    UserFollowersListView,
    UserFollowingListView,
    MyFollowersListView,
    MyFollowingListView,
    OtherUserProfileView,
    UserOutfitsListView,
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
    path('outfits/<int:pk>/', OutfitDetailView.as_view(), name='outfit-detail'),
    path('outfits/<int:pk>/like/', OutfitLikeToggleView.as_view(), name='outfit-like'),
    path('outfits/<int:pk>/likes/', OutfitLikersListView.as_view(), name='outfit-likers'),
    path('my-outfits/', MyOutfitsListView.as_view(), name='my-outfits'),
    path('outfits/liked/', LikedOutfitsListView.as_view(), name='outfits-liked'),
    path('outfits/calendar/', OutfitCalendarView.as_view(), name='outfits-calendar'),
    path('feed/', PublicNewsfeedView.as_view(), name='public-feed'),
    path('feed/following/', FollowingNewsfeedView.as_view(), name='following-feed'),
    path('explore/', ExploreNewsfeedView.as_view(), name='explore-feed'),
    path('your-day/', YourDayOutfitView.as_view(), name='your-day'),

    # Self profile direct following & followers
    path('following/', MyFollowingListView.as_view(), name='my-following'),
    path('followers/', MyFollowersListView.as_view(), name='my-followers'),

    # Follow / Unfollow system & user profile visit
    path('users/<str:user_id>/follow/', UserFollowToggleView.as_view(), name='user-follow'),
    path('users/<str:user_id>/followers/', UserFollowersListView.as_view(), name='user-followers'),
    path('users/<str:user_id>/following/', UserFollowingListView.as_view(), name='user-following'),
    path('users/<str:user_id>/profile/', OtherUserProfileView.as_view(), name='user-social-profile'),
    path('users/<str:user_id>/outfits/', UserOutfitsListView.as_view(), name='user-outfits-list'),

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
    path('messages/<str:user_id>/', DirectMessageConversationView.as_view(), name='message-conversation'),
]
