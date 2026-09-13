from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from collections import defaultdict

from social.models import UserFollow, DirectMessage, Story, StoryView, StoryLike
from social.serializers import (
    DirectMessageSerializer,
    UserSimpleSerializer,
    StorySerializer,
    StoryViewerSerializer,
)
from drf_spectacular.utils import extend_schema, OpenApiResponse

User = get_user_model()
from .outfit_views import StandardSocialPagination

def get_active_stories_for_user(request_user, request=None):
    """
    Fetch active stories within 24 hours for followed users and self,
    grouped by user for the story tray.
    """
    now = timezone.now()
    followed_user_ids = list(
        UserFollow.objects.filter(follower=request_user).values_list('following_id', flat=True)
    )
    relevant_user_ids = [request_user.id] + followed_user_ids

    active_stories = (
        Story.objects.filter(
            user_id__in=relevant_user_ids,
            is_active=True,
            expires_at__gt=now
        )
        .select_related('user')
        .prefetch_related('views__viewer', 'likes')
        .order_by('-created_at')
    )

    # Collect viewed story IDs for this user to avoid N+1 queries
    viewed_story_ids = set(
        StoryView.objects.filter(
            viewer=request_user,
            story__in=active_stories
        ).values_list('story_id', flat=True)
    )
    loved_story_ids = set(
        StoryLike.objects.filter(
            user=request_user,
            story__in=active_stories
        ).values_list('story_id', flat=True)
    )

    # Group stories by author
    from collections import defaultdict
    grouped = defaultdict(list)
    for story in active_stories:
        grouped[story.user_id].append(story)

    serializer_context = {
        'request': request,
        'viewed_story_ids': viewed_story_ids,
        'loved_story_ids': loved_story_ids,
    }

    groups = []
    # 1. User's own stories (always first if present)
    if request_user.id in grouped:
        user_stories = grouped[request_user.id]
        serialized_stories = StorySerializer(user_stories, many=True, context=serializer_context).data
        has_unseen = any(s.id not in viewed_story_ids for s in user_stories)
        groups.append({
            'user': UserSimpleSerializer(request_user, context={'request': request}).data,
            'has_unseen_story': has_unseen,
            'total_stories': len(user_stories),
            'stories': serialized_stories,
        })

    # 2. Followed users' stories
    followed_groups = []
    for uid in followed_user_ids:
        if uid in grouped:
            u_stories = grouped[uid]
            author = u_stories[0].user
            serialized_stories = StorySerializer(u_stories, many=True, context=serializer_context).data
            has_unseen = any(s.id not in viewed_story_ids for s in u_stories)
            followed_groups.append({
                'user': UserSimpleSerializer(author, context={'request': request}).data,
                'has_unseen_story': has_unseen,
                'total_stories': len(u_stories),
                'stories': serialized_stories,
            })

    # Sort followed groups: unseen first, then by latest story date
    followed_groups.sort(
        key=lambda g: (not g['has_unseen_story'], -(g['stories'][0]['id'] if g['stories'] else 0))
    )
    groups.extend(followed_groups)

    return groups

User = get_user_model()


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Create 24h Ephemeral Story",
    description="Upload and publish a 24-hour fashion story with photo and caption.",
    responses={
        201: StorySerializer,
        400: OpenApiResponse(description="Validation error or missing image"),
    }
)
class StoryCreateView(APIView):
    """
    API endpoint to upload/post a new story (24-hour expiration).
    
    POST /api/social/stories/
    Body (multipart/form-data):
    - image: file (required)
    - caption: string (optional)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        stories_data = get_active_stories_for_user(request.user, request=request)
        return Response({
            'success': True,
            'message': 'Active stories retrieved successfully.',
            'data': stories_data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        # Ensure media / file alias from request.FILES is populated
        for alias in ('media', 'file', 'media_file', 'picture', 'story_image'):
            if hasattr(request, 'FILES') and alias in request.FILES and 'image' not in request.FILES:
                data['image'] = request.FILES[alias]
                break
            elif alias in data and 'image' not in data:
                data['image'] = data[alias]
                break

        serializer = StorySerializer(data=data, context={'request': request})
        if serializer.is_valid():
            story = serializer.save(user=request.user)
            return Response({
                'success': True,
                'message': 'Story published successfully.',
                'data': StorySerializer(story, context={'request': request}).data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'success': False,
            'message': 'Validation failed.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Active Stories Tray (Feed)",
    description="Retrieve active 24-hour stories grouped by followed creators and current user.",
    responses={
        200: OpenApiResponse(description="Active stories grouped by author"),
    }
)
class StoryFeedView(APIView):
    """
    API endpoint to retrieve active stories (24 hours) grouped by user
    for the story tray (followed users + user's own stories).
    
    GET /api/social/stories/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        stories_data = get_active_stories_for_user(request.user, request=request)
        return Response({
            'success': True,
            'message': 'Active stories retrieved successfully.',
            'data': stories_data
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="List My Active Stories",
    description="Retrieve authenticated user's own active stories with viewer counts.",
    responses={
        200: StorySerializer(many=True),
    }
)
class MyStoriesListView(APIView):
    """
    API endpoint to retrieve authenticated user's own active stories with viewer counts.
    
    GET /api/social/stories/my/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        now = timezone.now()
        stories = (
            Story.objects.filter(user=request.user, is_active=True, expires_at__gt=now)
            .select_related('user')
            .prefetch_related('views__viewer', 'likes')
            .order_by('-created_at')
        )
        serializer = StorySerializer(stories, many=True, context={'request': request})
        return Response({
            'success': True,
            'message': 'My active stories retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Record Story View",
    description="Mark a 24-hour story as viewed by the authenticated user.",
    responses={
        200: OpenApiResponse(description="Story view recorded successfully"),
        410: OpenApiResponse(description="Story has expired"),
    }
)
class StoryViewRecordView(APIView):
    """
    API endpoint to record that the authenticated user has viewed a story.
    
    POST /api/social/stories/<pk>/view/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk)
        if story.is_expired or not story.is_active:
            return Response({
                'success': False,
                'message': 'This story has expired.'
            }, status=status.HTTP_410_GONE)

        # Self-view should not count as external viewer
        if story.user_id == request.user.id:
            return Response({
                'success': True,
                'message': 'Self view acknowledged.',
                'data': {
                    'story_id': story.id,
                    'views_count': story.views_count,
                    'is_first_view': False,
                }
            }, status=status.HTTP_200_OK)

        view_obj, created = StoryView.objects.get_or_create(story=story, viewer=request.user)
        return Response({
            'success': True,
            'message': 'Story view recorded.',
            'data': {
                'story_id': story.id,
                'views_count': story.views_count,
                'is_first_view': created,
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Toggle Story Reaction / Love",
    description="Love or unlove a 24-hour fashion story.",
    responses={
        200: OpenApiResponse(description="Reaction toggled successfully"),
        410: OpenApiResponse(description="Story has expired"),
    }
)
class StoryLikeToggleView(APIView):
    """
    API endpoint to love/heart or unlove a story.
    
    POST /api/social/stories/<pk>/like/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk)
        if story.is_expired or not story.is_active:
            return Response({
                'success': False,
                'message': 'This story has expired.'
            }, status=status.HTTP_410_GONE)

        like_obj, created = StoryLike.objects.get_or_create(story=story, user=request.user)
        if not created:
            like_obj.delete()
            is_loved = False
            msg = 'Story unloved.'
        else:
            StoryView.objects.get_or_create(story=story, viewer=request.user)
            is_loved = True
            msg = 'Story loved.'

        return Response({
            'success': True,
            'message': msg,
            'data': {
                'story_id': story.id,
                'has_loved': is_loved,
                'loves_count': story.loves_count,
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Reply to Story via Direct Message",
    description="Send an instant direct message reply to the story author.",
    responses={
        201: DirectMessageSerializer,
        400: OpenApiResponse(description="Self-reply or missing message content"),
        410: OpenApiResponse(description="Story has expired"),
    }
)
class StoryReplyView(APIView):
    """
    API endpoint to reply to a story with a message.
    Automatically creates a DirectMessage referencing the story, which appears
    in the story author's Inbox with the story preview.
    
    POST /api/social/stories/<pk>/reply/
    Body: {"content": "Looking amazing!"}
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        story = get_object_or_404(Story, pk=pk)
        if story.is_expired or not story.is_active:
            return Response({
                'success': False,
                'message': 'This story has expired.'
            }, status=status.HTTP_410_GONE)

        if story.user_id == request.user.id:
            return Response({
                'success': False,
                'message': 'You cannot reply to your own story.'
            }, status=status.HTTP_400_BAD_REQUEST)

        content = request.data.get('content', '').strip()

        if not content:
            return Response({
                'success': False,
                'message': 'content is required to reply to a story.'
            }, status=status.HTTP_400_BAD_REQUEST)

        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=story.user,
            message_type='story_reply',
            content=content,
            story_reference=story,
        )

        serializer = DirectMessageSerializer(message, context={'request': request})
        return Response({
            'success': True,
            'message': 'Reply sent to inbox.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="List Story Viewers & Likes",
    description="Owner-only endpoint to view list of users who viewed or loved their story.",
    responses={
        200: StoryViewerSerializer(many=True),
    }
)
class StoryViewersListView(generics.ListAPIView):
    """
    API endpoint for the story owner to see who viewed their story and who loved it.
    
    GET /api/social/stories/<pk>/viewers/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = StoryViewerSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        story_id = self.kwargs.get('pk')
        story = get_object_or_404(Story, pk=story_id)
        if story.user_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the story owner can view viewers.")
        return StoryView.objects.filter(story=story).select_related('viewer')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        story_id = self.kwargs.get('pk')
        context['loved_user_ids'] = set(
            StoryLike.objects.filter(story_id=story_id).values_list('user_id', flat=True)
        )
        return context



@extend_schema(
    tags=["Stories & Ephemeral Moments"],
    summary="Delete Story",
    description="Delete an active story before its 24h expiry.",
    responses={
        200: OpenApiResponse(description="Story deleted successfully"),
        404: OpenApiResponse(description="Story not found or not owner"),
    }
)
class StoryDeleteView(APIView):
    """
    API endpoint to delete authenticated user's own story.
    
    DELETE /api/social/stories/<pk>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def delete(self, request, pk):
        story = get_object_or_404(Story, pk=pk, user=request.user)
        story.delete()
        return Response({
            'success': True,
            'message': 'Story deleted successfully.'
        }, status=status.HTTP_200_OK)
