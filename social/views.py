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

from .models import TodayOutfit, OutfitLike, UserFollow, DirectMessage
from .serializers import (
    TodayOutfitSerializer,
    UserFollowSerializer,
    DirectMessageSerializer,
    UserSimpleSerializer,
    ConversationSummarySerializer,
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

        if recipient != request.user:
            try:
                from notifications.services import create_notification
                create_notification(
                    recipient=recipient,
                    sender=request.user,
                    notification_type='direct_message',
                    title='New Message',
                    message=f"{request.user.name or 'A user'}: {content[:60]}",
                    data={'sender_id': str(request.user.id), 'deep_link': f"closly://chat/{request.user.id}"}
                )
            except Exception:
                pass

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

        return (
            DirectMessage.objects.filter(
                (Q(sender=current_user) & Q(recipient_id=other_user_id)) |
                (Q(sender_id=other_user_id) & Q(recipient=current_user))
            )
            .select_related('sender', 'recipient')
        )


class ConversationListView(APIView):
    """
    API endpoint to list user's conversation threads (Inbox).
    Returns all conversations grouped by partner user, ordered by latest message time.
    Includes partner user details, latest message preview, and unread count.

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

        return Response({
            'success': True,
            'message': 'Conversations retrieved successfully.',
            'data': serializer.data
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




