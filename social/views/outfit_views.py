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
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

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


KNOWN_STYLES = ['minimalist', 'streetwear', 'casual', 'chic', 'classic', 'formal', 'bohemian', 'vintage', 'sporty', 'adjacent']
KNOWN_WEATHER = ['warm', 'cool', 'chilly', 'cold', 'hot', 'rainy', 'mild', 'sunny']


def infer_style_category(user, caption, explicit_style=None):
    """
    Determines the style category for an outfit:
    1. Explicitly supplied by user/client
    2. Inferred from hashtags/keywords in caption
    3. Inferred from user's Style DNA onboarding preferences
    4. Fallback default: 'casual'
    """
    if explicit_style and str(explicit_style).strip():
        return str(explicit_style).strip().lower()

    if caption:
        caption_lower = caption.lower()
        for style in KNOWN_STYLES:
            if style in caption_lower:
                return style

    if hasattr(user, 'preferences') and user.preferences and user.preferences.style_match:
        styles = user.preferences.style_match
        if isinstance(styles, list) and len(styles) > 0:
            return str(styles[0]).lower()
        elif isinstance(styles, str) and styles.strip():
            return styles.strip().lower()

    return 'casual'


def infer_weather_tag(user, caption, explicit_weather=None):
    """
    Determines the weather tag for an outfit:
    1. Explicitly supplied by user/client
    2. Inferred from keywords in caption
    3. Inferred from live local weather for the user
    4. Fallback default: 'mild'
    """
    if explicit_weather and str(explicit_weather).strip():
        return str(explicit_weather).strip().lower()

    if caption:
        caption_lower = caption.lower()
        for w in KNOWN_WEATHER:
            if w in caption_lower:
                return w

    try:
        from social.your_day import get_live_weather
        weather = get_live_weather(user=user)
        vibe = weather.get('weather_vibe')
        if vibe and str(vibe).lower() in KNOWN_WEATHER:
            return str(vibe).lower()
        cond = weather.get('condition')
        if cond:
            cond_lower = str(cond).lower()
            if 'rain' in cond_lower:
                return 'rainy'
            elif 'snow' in cond_lower or 'cold' in cond_lower:
                return 'chilly'
            elif 'sun' in cond_lower or 'clear' in cond_lower:
                return 'warm'
    except Exception:
        pass

    return 'mild'


@extend_schema(
    tags=["Outfits & Looks"],
    summary="Post Today's Look / Outfit",
    description="Create and publish a daily outfit lookbook entry with multiple photos, tagged wardrobe items, and caption.",
    responses={
        201: TodayOutfitSerializer,
        400: OpenApiResponse(description="Validation error"),
    }
)
class TodayOutfitCreateView(generics.CreateAPIView):
    """
    API endpoint for uploading today's outfit.
    
    POST /api/social/outfits/
    Body: multipart/form-data (image, caption, visibility ['public'|'private'], style_category, weather_tag, tagged_items)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = TodayOutfitSerializer

    def perform_create(self, serializer):
        user = self.request.user
        caption = serializer.validated_data.get('caption', '')
        explicit_style = serializer.validated_data.get('style_category')
        explicit_weather = serializer.validated_data.get('weather_tag')

        style_cat = infer_style_category(user, caption, explicit_style)
        weather_tag = infer_weather_tag(user, caption, explicit_weather)

        outfit = serializer.save(
            user=user,
            style_category=style_cat,
            weather_tag=weather_tag
        )
        try:
            from rewards.services import award_points
            award_points(
                user=user,
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


@extend_schema(
    tags=["Outfits & Looks"],
    summary="List My Created Outfits",
    description="Retrieve paginated list of outfits created by the authenticated user (both public and private).",
    responses={
        200: TodayOutfitSerializer(many=True),
    }
)
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
            .prefetch_related('tagged_items', 'images')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [o.id for o in page]
            context = super().get_serializer_context()
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=request.user, outfit_id__in=page_ids).values_list('outfit_id', flat=True)
            )
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        context = super().get_serializer_context()
        if request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=request.user, outfit_id__in=[o.id for o in queryset]).values_list('outfit_id', flat=True)
            )
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)



@extend_schema(
    tags=["Outfits & Looks"],
    summary="Toggle Outfit Like",
    description="Like or unlike an outfit post.",
    responses={
        200: OpenApiResponse(description="Like status updated successfully"),
        403: OpenApiResponse(description="Cannot interact with private outfit"),
        404: OpenApiResponse(description="Outfit not found"),
    }
)
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



@extend_schema(
    tags=["Outfits & Looks"],
    summary="List Liked Outfits",
    description="Retrieve paginated list of outfits liked by the authenticated user (excluding self-outfits).",
    responses={
        200: TodayOutfitSerializer(many=True),
    }
)
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
            TodayOutfit.objects.filter(likes__user=self.request.user, visibility='public')
            .exclude(user=self.request.user)
            .select_related('user')
            .prefetch_related('tagged_items', 'images')
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


@extend_schema(
    tags=["Outfits & Looks"],
    summary="Outfit Calendar History",
    description="Monthly calendar view of logged outfits for wardrobe rotation and style consistency tracking.",
    parameters=[
        OpenApiParameter('year', int, description="Calendar year (e.g. 2026)"),
        OpenApiParameter('month', int, description="Calendar month (1 - 12)"),
    ],
    responses={
        200: OpenApiResponse(description="Calendar days with logged outfit thumbnails and counts"),
    }
)
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

        outfits = list(
            TodayOutfit.objects.filter(
                user=request.user,
                created_at__year=year,
                created_at__month=month
            )
            .select_related('user')
            .prefetch_related('tagged_items', 'images')
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
                'total_outfits': len(outfits),
                'days': days_map
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Outfits & Looks"],
    summary="Outfit Details (Get / Update / Delete)",
    description="Retrieve full details for an outfit post, update post metadata (author only), or delete it.",
    responses={
        200: TodayOutfitSerializer,
        403: OpenApiResponse(description="Permission denied"),
        404: OpenApiResponse(description="Outfit not found"),
    }
)
class OutfitDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    API endpoint to retrieve, update (PATCH/PUT), or delete an outfit post.
    
    GET /api/social/outfits/<id>/ (Public post, or private if requested by author)
    PATCH /api/social/outfits/<id>/ (Author only: partial update)
    PUT /api/social/outfits/<id>/ (Author only: full update)
    DELETE /api/social/outfits/<id>/ (Author only: delete)
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
            .prefetch_related('tagged_items', 'images')
            .annotate(_likes_count=Count('likes', distinct=True))
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            raw_req = getattr(self.request, '_request', self.request)
            if not hasattr(raw_req, '_cached_liked_outfit_ids'):
                lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
                pk = self.kwargs.get(lookup_url_kwarg) or self.kwargs.get('pk')
                if pk:
                    is_liked = OutfitLike.objects.filter(user_id=self.request.user.id, outfit_id=pk).exists()
                    raw_req._cached_liked_outfit_ids = {int(pk)} if is_liked else set()
                else:
                    raw_req._cached_liked_outfit_ids = set(
                        OutfitLike.objects.filter(user_id=self.request.user.id).values_list('outfit_id', flat=True)
                    )
            context['liked_outfit_ids'] = raw_req._cached_liked_outfit_ids
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Outfit details retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        if instance.user != request.user:
            return Response({
                'success': False,
                'message': 'You can only edit your own outfits.'
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Outfit post updated successfully.',
                'data': serializer.data
            }, status=status.HTTP_200_OK)
        return Response({
            'success': False,
            'message': 'Failed to update outfit post.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

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


@extend_schema(
    tags=["Outfits & Looks"],
    summary="List Outfit Likers",
    description="Retrieve list of users who liked a specific outfit post, including follow status.",
    responses={
        200: OpenApiResponse(description="List of likers with follow state"),
        404: OpenApiResponse(description="Outfit not found"),
    }
)
class OutfitLikersListView(APIView):
    """
    API endpoint to view users who liked a specific outfit post.
    
    GET /api/social/outfits/<id>/likes/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request, pk):
        outfit = get_object_or_404(TodayOutfit, pk=pk)
        likers = list(User.objects.filter(outfit_likes__outfit=outfit).select_related('reward_profile'))
        
        # Batch following check in a single query (eliminates N+1 query)
        following_user_ids = set(
            UserFollow.objects.filter(follower=request.user, following__in=likers).values_list('following_id', flat=True)
        )

        likers_data = []
        for u in likers:
            pic_url = u.profile_picture.url if u.profile_picture else None
            if pic_url and not pic_url.startswith(('http://', 'https://')):
                pic_url = request.build_absolute_uri(pic_url)
            likers_data.append({
                'id': str(u.id),
                'name': u.name,
                'email': u.email,
                'profile_picture': pic_url,
                'is_following': (u.id in following_user_ids),
            })

        return Response({
            'success': True,
            'message': f"Users who liked outfit {pk} retrieved successfully.",
            'total_count': len(likers),
            'data': likers_data
        }, status=status.HTTP_200_OK)


