from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q, Count
from django.utils import timezone

from .models import TodayOutfit, OutfitLike, UserFollow, DirectMessage, Story, StoryView, StoryLike
from affiliate.models import AffiliateProduct
from .serializers import (
    TodayOutfitSerializer,
    UserFollowSerializer,
    DirectMessageSerializer,
    UserSimpleSerializer,
    ConversationSummarySerializer,
    StorySerializer,
    UserStoryGroupSerializer,
    StoryViewerSerializer,
)


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
        .prefetch_related('views', 'likes')
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
        outfit = serializer.save(user=self.request.user)
        try:
            from rewards.services import award_points
            award_points(
                user=self.request.user,
                action_type='share_look',
                description="Shared a today outfit look",
                reference_id=str(outfit.id)
            )
        except Exception:
            pass

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
        return (
            TodayOutfit.objects.filter(user=self.request.user)
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context


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
        # Public posts only with optimized prefetching and like count annotation
        return (
            TodayOutfit.objects.filter(visibility='public')
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context


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
        # Filter public posts from followed users with optimized prefetching
        return (
            TodayOutfit.objects.filter(user_id__in=following_user_ids, visibility='public')
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context


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
            if outfit.user != request.user:
                try:
                    from notifications.services import create_notification
                    create_notification(
                        recipient=outfit.user,
                        sender=request.user,
                        notification_type='outfit_like',
                        title='New Outfit Like',
                        message=f"{request.user.name or 'A user'} liked your outfit look.",
                        data={'outfit_id': outfit.id, 'deep_link': f"closly://outfit/{outfit.id}"}
                    )
                except Exception:
                    pass

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
            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=target_user,
                    sender=request.user,
                    notification_type='new_follower',
                    title='New Follower',
                    message=f"{request.user.name or 'A user'} started following you.",
                    data={'user_id': str(request.user.id), 'deep_link': f"closly://user/{request.user.id}"}
                )
            except Exception:
                pass

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
    Supports tab filtering:
    - ?tab=all (default, all followers with DNA match scores)
    - ?tab=dna_match (sorted descending by DNA match score %)
    - ?tab=new_followers (followed within the last 14 days)
    - ?tab=same_location (same city, district, or country)
    
    GET /api/social/users/<user_id>/followers/?tab=dna_match
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = UserFollowSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['view_type'] = 'followers'
        return ctx

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        if not user_id or str(user_id) == 'me':
            user_id = self.request.user.id

        qs = UserFollow.objects.filter(following_id=user_id).select_related(
            'follower', 'following', 'follower__preferences', 'following__preferences'
        )
        tab = self.request.query_params.get('tab', 'all').lower()

        if tab == 'new_followers':
            cutoff = timezone.now() - timezone.timedelta(days=14)
            qs = qs.filter(created_at__gte=cutoff)
        elif tab == 'same_location':
            u = self.request.user
            q_loc = Q()
            if u.city:
                q_loc |= Q(follower__city__iexact=u.city.strip())
            if u.country:
                q_loc |= Q(follower__country__iexact=u.country.strip())
            if q_loc:
                qs = qs.filter(q_loc)

        return qs.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        tab = request.query_params.get('tab', 'all').lower()
        if tab == 'dna_match' and isinstance(response.data, list):
            response.data.sort(
                key=lambda x: (x.get('dna_match') or {}).get('score', 0),
                reverse=True
            )
        return response


class UserFollowingListView(generics.ListAPIView):
    """
    API endpoint to list users followed by a user.
    Supports tab filtering:
    - ?tab=all
    - ?tab=dna_match (sorted descending by DNA match score %)
    - ?tab=new_followers (followed within last 14 days)
    - ?tab=same_location (same city, district, or country)
    
    GET /api/social/users/<user_id>/following/?tab=all
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = UserFollowSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['view_type'] = 'following'
        return ctx

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        if not user_id or str(user_id) == 'me':
            user_id = self.request.user.id

        qs = UserFollow.objects.filter(follower_id=user_id).select_related(
            'follower', 'following', 'follower__preferences', 'following__preferences'
        )
        tab = self.request.query_params.get('tab', 'all').lower()

        if tab == 'new_followers':
            cutoff = timezone.now() - timezone.timedelta(days=14)
            qs = qs.filter(created_at__gte=cutoff)
        elif tab == 'same_location':
            u = self.request.user
            q_loc = Q()
            if u.city:
                q_loc |= Q(following__city__iexact=u.city.strip())
            if u.country:
                q_loc |= Q(following__country__iexact=u.country.strip())
            if q_loc:
                qs = qs.filter(q_loc)

        return qs.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        tab = request.query_params.get('tab', 'all').lower()
        if tab == 'dna_match' and isinstance(response.data, list):
            response.data.sort(
                key=lambda x: (x.get('dna_match') or {}).get('score', 0),
                reverse=True
            )
        return response


class MyFollowingListView(UserFollowingListView):
    """
    Direct endpoint for authenticated user to see who they follow (Self Profile).
    
    GET /api/social/following/?tab=all|dna_match|new_followers|same_location
    """
    def get_queryset(self):
        self.kwargs['user_id'] = self.request.user.id
        return super().get_queryset()


class MyFollowersListView(UserFollowersListView):
    """
    Direct endpoint for authenticated user to see their followers (Self Profile).
    
    GET /api/social/followers/?tab=all|dna_match|new_followers|same_location
    """
    def get_queryset(self):
        self.kwargs['user_id'] = self.request.user.id
        return super().get_queryset()


class OtherUserProfileView(APIView):
    """
    API endpoint to view another user's profile with real-time Style DNA match percentage.
    
    GET /api/social/users/<user_id>/profile/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request, user_id):
        target_user = get_object_or_404(
            User.objects.select_related('preferences', 'reward_profile'),
            pk=user_id
        )
        is_following = UserFollow.objects.filter(follower=request.user, following=target_user).exists()
        is_self = (request.user.id == target_user.id)

        from .dna import calculate_dna_match
        dna = calculate_dna_match(request.user, target_user)

        reward_profile = getattr(target_user, 'reward_profile', None)
        tier = reward_profile.current_tier if reward_profile else 'Bronze'

        followers_count = UserFollow.objects.filter(following=target_user).count()
        following_count = UserFollow.objects.filter(follower=target_user).count()
        outfit_count = TodayOutfit.objects.filter(user=target_user, visibility='public').count()
        closet_count = target_user.closet_items.count()

        pic_url = target_user.profile_picture.url if target_user.profile_picture else None
        if pic_url and not pic_url.startswith(('http://', 'https://')):
            pic_url = request.build_absolute_uri(pic_url)

        return Response({
            'success': True,
            'message': f"Profile of {target_user.name or 'User'} retrieved successfully.",
            'data': {
                'id': str(target_user.id),
                'name': target_user.name,
                'email': target_user.email,
                'bio': target_user.bio or '',
                'country': target_user.country or '',
                'city': target_user.city or '',
                'profile_picture': pic_url,
                'current_tier': tier,
                'is_self': is_self,
                'is_following': is_following,
                'followers_count': followers_count,
                'following_count': following_count,
                'outfit_count': outfit_count,
                'closet_count': closet_count,
                'dna_match': dna,
            }
        }, status=status.HTTP_200_OK)


class DirectMessageSendView(APIView):
    """
    API endpoint to send a direct message to a user.
    Supports text, image attachments, shared products, shared outfits, and story replies.
    
    POST /api/social/messages/
    Body (multipart/form-data or JSON):
    - recipient_id: UUID (required)
    - message_type: 'text' | 'image' | 'product' | 'outfit' | 'story_reply' (optional)
    - content: string (optional if attachment/shared item is provided)
    - image: file (optional, image attachment)
    - product_id: int (optional, shared AffiliateProduct)
    - outfit_id: int (optional, shared TodayOutfit)
    - story_id: int (optional, replied Story)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        recipient_id = request.data.get('recipient_id')
        message_type = request.data.get('message_type', 'text')
        content = request.data.get('content', '')
        image_file = request.FILES.get('image')
        product_id = request.data.get('product_id')
        outfit_id = request.data.get('outfit_id')
        story_id = request.data.get('story_id')

        if not recipient_id:
            return Response({
                'success': False,
                'message': 'recipient_id is required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        recipient = get_object_or_404(User, pk=recipient_id)

        shared_product = None
        if product_id:
            shared_product = get_object_or_404(AffiliateProduct, pk=product_id)
            message_type = 'product'

        shared_outfit = None
        if outfit_id:
            shared_outfit = get_object_or_404(TodayOutfit, pk=outfit_id)
            message_type = 'outfit'

        story_ref = None
        if story_id:
            story_ref = get_object_or_404(Story, pk=story_id)
            message_type = 'story_reply'

        if image_file:
            message_type = 'image'

        if not content and not image_file and not shared_product and not shared_outfit and not story_ref:
            return Response({
                'success': False,
                'message': 'Message must contain text content, an image, or a shared item.'
            }, status=status.HTTP_400_BAD_REQUEST)

        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            message_type=message_type,
            content=content or '',
            image=image_file,
            shared_product=shared_product,
            shared_outfit=shared_outfit,
            story_reference=story_ref,
        )

        if recipient != request.user:
            try:
                from notifications.services import create_notification
                preview_text = content[:60] if content else f"Shared a {message_type}"
                create_notification(
                    recipient=recipient,
                    sender=request.user,
                    notification_type='direct_message',
                    title='New Message',
                    message=f"{request.user.name or 'A user'}: {preview_text}",
                    data={'sender_id': str(request.user.id), 'deep_link': f"closly://chat/{request.user.id}"}
                )
            except Exception:
                pass

        serializer = DirectMessageSerializer(message, context={'request': request})
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

        return (
            DirectMessage.objects.filter(
                (Q(sender=current_user) & Q(recipient_id=other_user_id)) |
                (Q(sender_id=other_user_id) & Q(recipient=current_user))
            )
            .select_related('sender', 'recipient', 'shared_product', 'shared_outfit', 'shared_outfit__user', 'story_reference', 'story_reference__user')
        )


class ConversationListView(APIView):
    """
    API endpoint to list user's conversation threads (Inbox) + Active Stories Tray.
    Returns all conversations grouped by partner user, ordered by latest message time,
    along with active stories of followed users for the top story bar.

    GET /api/social/conversations/
    GET /api/social/messages/inbox/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user

        # 1. Fetch unread counts grouped by sender in 1 query
        unread_counts_qs = (
            DirectMessage.objects.filter(recipient=user, is_read=False)
            .values('sender_id')
            .annotate(count=Count('id'))
        )
        unread_map = {item['sender_id']: item['count'] for item in unread_counts_qs}

        # 2. Fetch all messages involving user, ordered newest first with related users
        messages = (
            DirectMessage.objects.filter(Q(sender=user) | Q(recipient=user))
            .select_related('sender', 'recipient')
            .order_by('-created_at', '-id')
        )

        # 3. Deduplicate by conversation partner while preserving latest message
        conversations = {}
        for msg in messages:
            partner = msg.recipient if msg.sender_id == user.id else msg.sender
            if partner.id not in conversations:
                conversations[partner.id] = {
                    'other_user': partner,
                    'last_message': {
                        'id': msg.id,
                        'message_type': msg.message_type,
                        'content': msg.content,
                        'sender_id': str(msg.sender_id),
                        'created_at': msg.created_at,
                        'is_read': msg.is_read,
                    },
                    'unread_count': unread_map.get(partner.id, 0),
                }

        serializer = ConversationSummarySerializer(
            list(conversations.values()),
            many=True,
            context={'request': request}
        )

        # Fetch active stories for the top horizontal story bar
        stories_data = get_active_stories_for_user(user, request=request)

        return Response({
            'success': True,
            'message': 'Conversations and stories retrieved successfully.',
            'data': serializer.data,
            'stories': stories_data,
        }, status=status.HTTP_200_OK)


class LikedOutfitsListView(generics.ListAPIView):
    """
    API endpoint to list outfits liked by the authenticated user.
    Note: As per user specification, self-outfits are excluded from this list.
    
    GET /api/social/outfits/liked/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        return (
            TodayOutfit.objects.filter(likes__user=self.request.user)
            .exclude(user=self.request.user)
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-likes__created_at')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context


class OutfitCalendarView(APIView):
    """
    API endpoint to retrieve calendar-wise outfits for a given month and year.
    Returns outfits grouped by date (YYYY-MM-DD) for rendering in calendar cells.
    
    GET /api/social/outfits/calendar/?year=2026&month=9
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        now = timezone.now()
        year_param = request.query_params.get('year')
        month_param = request.query_params.get('month')

        try:
            year = int(year_param) if (year_param and str(year_param).strip()) else now.year
            month = int(month_param) if (month_param and str(month_param).strip()) else now.month
            if not (1 <= month <= 12 and 1900 <= year <= 2100):
                year, month = now.year, now.month
        except (ValueError, TypeError):
            year, month = now.year, now.month

        outfits = (
            TodayOutfit.objects.filter(
                user=request.user,
                created_at__year=year,
                created_at__month=month
            )
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('created_at')
        )

        days_map = {}
        for outfit in outfits:
            date_str = outfit.created_at.strftime('%Y-%m-%d')
            if date_str not in days_map:
                days_map[date_str] = []

            img_url = outfit.image.url if outfit.image else None
            if img_url and not img_url.startswith(('http://', 'https://')):
                img_url = request.build_absolute_uri(img_url)

            days_map[date_str].append({
                'id': outfit.id,
                'image': img_url,
                'caption': outfit.caption,
                'visibility': outfit.visibility,
                'likes_count': outfit.likes_count,
                'created_at': outfit.created_at.isoformat(),
            })

        return Response({
            'success': True,
            'message': 'Calendar outfits retrieved successfully.',
            'data': {
                'year': year,
                'month': month,
                'is_running_month': (year == now.year and month == now.month),
                'total_outfits': outfits.count(),
                'days': days_map
            }
        }, status=status.HTTP_200_OK)


class YourDayOutfitView(APIView):
    """
    API endpoint for 'Your Day' screen.
    Returns:
    1. Today's live weather widget (day, date, temp, humidity, wind, pressure, condition).
    2. Smart daily outfit suggestion from the user's own digital wardrobe (top to bottom).
    3. Personalized stylist explanation for why this outfit matches today's conditions.
    
    GET /api/social/your-day/?lat=23.8103&lon=90.4125
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        lat = request.query_params.get('lat')
        lon = request.query_params.get('lon')
        city = request.query_params.get('city')

        from .your_day import get_live_weather, suggest_daily_outfit
        weather = get_live_weather(lat=lat, lon=lon, city=city, user=request.user)
        outfit_suggestion = suggest_daily_outfit(user=request.user, weather=weather, request=request)

        return Response({
            'success': True,
            'message': "Today's weather and smart daily outfit recommendation generated.",
            'data': {
                'weather': {
                    'day': weather['day'],
                    'date': weather['date'],
                    'city': weather['city'],
                    'temp': weather['temp'],
                    'condition': weather['condition'],
                    'weather_vibe': weather['weather_vibe'],
                    'humidity': weather['humidity'],
                    'wind': weather['wind'],
                    'pressure': weather['pressure'],
                    'icon': weather['icon']
                },
                'suggested_outfit_today': {
                    'pieces': outfit_suggestion['pieces'],
                    'total_pieces': outfit_suggestion['total_pieces_selected'],
                    'styling_description': outfit_suggestion['styling_description'],
                    'quick_action': {
                        'action': 'wear_today',
                        'item_ids': outfit_suggestion['item_ids_for_wear_today'],
                        'endpoint': '/api/closet/items/<id>/wear-today/'
                    }
                }
            }
        }, status=status.HTTP_200_OK)


class ExploreNewsfeedView(generics.ListAPIView):
    """
    API endpoint for Explore Feed.
    Shows trending public outfits from creators the user does NOT already follow.
    Supports category tabs:
    - trending (default: time-decayed engagement ranking)
    - adjacent (outfits from creators sharing Style DNA)
    - minimalist, streetwear, classic, chic, casual, formal (by caption / style tags)

    GET /api/social/explore/?category=trending
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        user = self.request.user
        category = self.request.query_params.get('category', 'trending').lower().strip()

        # Exclude self and users the current user already follows
        following_ids = list(
            UserFollow.objects.filter(follower=user).values_list('following_id', flat=True)
        )
        following_ids.append(user.id)

        qs = (
            TodayOutfit.objects.filter(visibility='public')
            .exclude(user_id__in=following_ids)
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
        )

        if category == 'adjacent':
            if hasattr(user, 'preferences') and user.preferences.style_match:
                styles = user.preferences.style_match
                style_q = Q()
                for s in styles:
                    style_q |= Q(user__preferences__style_match__icontains=s) | Q(caption__icontains=s)
                matched_qs = qs.filter(style_q)
                if matched_qs.exists():
                    qs = matched_qs
            return qs.order_by('-_likes_count', '-created_at')

        elif category in ('minimalist', 'streetwear', 'classic', 'chic', 'casual', 'formal', 'bohemian', 'sporty'):
            cat_q = Q(caption__icontains=category) | Q(user__preferences__style_match__icontains=category)
            filtered = qs.filter(cat_q)
            if filtered.exists():
                return filtered.order_by('-_likes_count', '-created_at')

        return qs.order_by('-_likes_count', '-created_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data['available_categories'] = [
            {"id": "trending", "label": "Trending Looks"},
            {"id": "adjacent", "label": "Style DNA Match"},
            {"id": "minimalist", "label": "Minimalist"},
            {"id": "streetwear", "label": "Streetwear"},
            {"id": "classic", "label": "Classic"},
            {"id": "chic", "label": "Chic & Elegant"},
            {"id": "casual", "label": "Casual Everyday"},
        ]
        response.data['active_category'] = request.query_params.get('category', 'trending')
        response.data['message'] = "Explore feed retrieved successfully."
        return response


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
        serializer = StorySerializer(data=request.data, context={'request': request})
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
            .prefetch_related('views', 'likes')
            .order_by('-created_at')
        )
        serializer = StorySerializer(stories, many=True, context={'request': request})
        return Response({
            'success': True,
            'message': 'My active stories retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)


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

        like_qs = StoryLike.objects.filter(story=story, user=request.user)
        if like_qs.exists():
            like_qs.delete()
            is_loved = False
            msg = 'Story unloved.'
        else:
            StoryLike.objects.create(story=story, user=request.user)
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
