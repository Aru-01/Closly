from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from social.models import UserFollow, TodayOutfit
from social.serializers import UserFollowSerializer

User = get_user_model()
from social.dna import calculate_dna_match

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

        try:
            target_user = get_object_or_404(User, pk=user_id)
        except (ValidationError, ValueError):
            return Response({
                'success': False,
                'message': 'Invalid user ID format.'
            }, status=status.HTTP_400_BAD_REQUEST)

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

        from social.dna import calculate_dna_match
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


