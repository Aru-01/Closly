from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import TodayOutfit, OutfitLike, UserFollow, DirectMessage
from .serializers import (
    TodayOutfitSerializer,
    UserFollowSerializer,
    DirectMessageSerializer,
    UserSimpleSerializer,
)

User = get_user_model()

class StandardSocialPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            'success': True,
            'message': 'Feed retrieved successfully.',
            'data': {
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
                'results': data
            }
        }, status=status.HTTP_200_OK)


class TodayOutfitCreateView(generics.CreateAPIView):
    """
    API endpoint for uploading today's outfit.
    
    POST /api/social/outfits/
    Body: multipart/form-data (image, caption, visibility ['public'|'private'])
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            self.perform_create(serializer)
            return Response({
                'success': True,
                'message': "Today's outfit posted successfully.",
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'success': False,
            'message': 'Failed to post outfit.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class MyOutfitsListView(generics.ListAPIView):
    """
    API endpoint to list user's own outfit history (both private and public).
    
    GET /api/social/my-outfits/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        return TodayOutfit.objects.filter(user=self.request.user)


class PublicNewsfeedView(generics.ListAPIView):
    """
    API endpoint for the global public newsfeed of public today outfit posts.
    
    GET /api/social/feed/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        # Public posts only
        return TodayOutfit.objects.filter(visibility='public')


class FollowingNewsfeedView(generics.ListAPIView):
    """
    API endpoint for filtering newsfeed to show ONLY outfit posts from followed users.
    
    GET /api/social/feed/following/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        # Get IDs of users current user is following
        following_user_ids = UserFollow.objects.filter(follower=self.request.user).values_list('following_id', flat=True)
        # Filter public posts from followed users
        return TodayOutfit.objects.filter(user_id__in=following_user_ids, visibility='public')


class OutfitLikeToggleView(APIView):
    """
    API endpoint to like or unlike a public outfit post.
    
    POST /api/social/outfits/<id>/like/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        outfit = get_object_or_404(TodayOutfit, pk=pk)
        if outfit.visibility != 'public' and outfit.user != request.user:
            return Response({
                'success': False,
                'message': 'Cannot interact with a private outfit post.'
            }, status=status.HTTP_403_FORBIDDEN)

        like, created = OutfitLike.objects.get_or_create(outfit=outfit, user=request.user)
        if not created:
            # Already liked -> Unlike
            like.delete()
            is_liked = False
            message = "Unliked outfit post."
        else:
            is_liked = True
            message = "Liked outfit post."

        return Response({
            'success': True,
            'message': message,
            'data': {
                'outfit_id': outfit.id,
                'likes_count': outfit.likes_count,
                'is_liked': is_liked
            }
        }, status=status.HTTP_200_OK)


class UserFollowToggleView(APIView):
    """
    API endpoint to follow or unfollow another user.
    
    POST /api/social/users/<user_id>/follow/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, user_id):
        if str(request.user.id) == str(user_id):
            return Response({
                'success': False,
                'message': 'You cannot follow yourself.'
            }, status=status.HTTP_400_BAD_REQUEST)

        target_user = get_object_or_404(User, pk=user_id)
        follow, created = UserFollow.objects.get_or_create(follower=request.user, following=target_user)

        if not created:
            # Unfollow
            follow.delete()
            is_following = False
            message = f"Unfollowed {target_user.name}."
        else:
            is_following = True
            message = f"Now following {target_user.name}."

        return Response({
            'success': True,
            'message': message,
            'data': {
                'user_id': str(target_user.id),
                'is_following': is_following
            }
        }, status=status.HTTP_200_OK)


class UserFollowersListView(generics.ListAPIView):
    """
    API endpoint to list followers of a user.
    
    GET /api/social/users/<user_id>/followers/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = UserFollowSerializer

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        return UserFollow.objects.filter(following_id=user_id)


class UserFollowingListView(generics.ListAPIView):
    """
    API endpoint to list users followed by a user.
    
    GET /api/social/users/<user_id>/following/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = UserFollowSerializer

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        return UserFollow.objects.filter(follower_id=user_id)


class DirectMessageSendView(APIView):
    """
    API endpoint to send a direct message to a user.
    
    POST /api/social/messages/
    Body: {"recipient_id": "uuid", "content": "Hello!"}
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        recipient_id = request.data.get('recipient_id')
        content = request.data.get('content')

        if not recipient_id or not content:
            return Response({
                'success': False,
                'message': 'recipient_id and content are required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        recipient = get_object_or_404(User, pk=recipient_id)
        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            content=content
        )

        serializer = DirectMessageSerializer(message)
        return Response({
            'success': True,
            'message': 'Message sent successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


class DirectMessageConversationView(generics.ListAPIView):
    """
    API endpoint to retrieve full conversation messages between current user and a target user.
    
    GET /api/social/messages/<user_id>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = DirectMessageSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        other_user_id = self.kwargs.get('user_id')
        current_user = self.request.user
        
        # Mark received messages from this user as read
        DirectMessage.objects.filter(sender_id=other_user_id, recipient=current_user, is_read=False).update(is_read=True)

        return DirectMessage.objects.filter(
            (Q(sender=current_user) & Q(recipient_id=other_user_id)) |
            (Q(sender_id=other_user_id) & Q(recipient=current_user))
        )
