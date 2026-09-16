from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from social.models import TodayOutfit, OutfitLike, UserFollow
from social.serializers import TodayOutfitSerializer

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

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            # In LikedOutfitsListView, all outfits on the page were liked by request.user
            context = super().get_serializer_context()
            context['liked_outfit_ids'] = {o.id for o in page}
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        context = super().get_serializer_context()
        context['liked_outfit_ids'] = {o.id for o in queryset}
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)


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


class OutfitDetailView(generics.RetrieveDestroyAPIView):
    """
    API endpoint to retrieve single outfit post details or delete own outfit post.
    
    GET /api/social/outfits/<id>/
    DELETE /api/social/outfits/<id>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer

    def get_queryset(self):
        user = self.request.user
        return (
            TodayOutfit.objects.filter(
                Q(visibility='public') | Q(user=user)
            )
            .select_related('user')
            .prefetch_related('tagged_items')
            .annotate(_likes_count=Count('likes', distinct=True))
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=self.request.user).values_list('outfit_id', flat=True)
            )
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Outfit details retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            return Response({
                'success': False,
                'message': 'You can only delete your own outfits.'
            }, status=status.HTTP_403_FORBIDDEN)
        instance.delete()
        return Response({
            'success': True,
            'message': 'Outfit post deleted successfully.'
        }, status=status.HTTP_200_OK)


class OutfitLikersListView(APIView):
    """
    API endpoint to view users who liked a specific outfit post.
    
    GET /api/social/outfits/<id>/likes/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request, pk):
        outfit = get_object_or_404(TodayOutfit, pk=pk)
        likers = User.objects.filter(outfit_likes__outfit=outfit).select_related('reward_profile')
        
        likers_data = []
        for u in likers:
            pic_url = u.profile_picture.url if u.profile_picture else None
            if pic_url and not pic_url.startswith(('http://', 'https://')):
                pic_url = request.build_absolute_uri(pic_url)
            is_following = UserFollow.objects.filter(follower=request.user, following=u).exists()
            likers_data.append({
                'id': str(u.id),
                'name': u.name,
                'email': u.email,
                'profile_picture': pic_url,
                'is_following': is_following,
            })

        return Response({
            'success': True,
            'message': f"Users who liked outfit {pk} retrieved successfully.",
            'data': likers_data
        }, status=status.HTTP_200_OK)


