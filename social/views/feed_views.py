from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model
from django.db.models import Q, Count

from social.models import TodayOutfit, OutfitLike, UserFollow
from social.serializers import TodayOutfitSerializer

User = get_user_model()
from social.your_day import get_live_weather, suggest_daily_outfit
from .outfit_views import StandardSocialPagination

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
            .prefetch_related('tagged_items', 'images')
            .annotate(_likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [o.id for o in page]
            liked_ids = set(
                OutfitLike.objects.filter(
                    user=request.user,
                    outfit_id__in=page_ids
                ).values_list('outfit_id', flat=True)
            )
            context = super().get_serializer_context()
            context['liked_outfit_ids'] = liked_ids
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        context = super().get_serializer_context()
        if request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=request.user, outfit_id__in=[o.id for o in queryset]).values_list('outfit_id', flat=True)
            )
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)


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
        # Filter public posts from followed users via subquery for single-query efficiency
        following_subquery = UserFollow.objects.filter(follower=self.request.user).values('following_id')
        return (
            TodayOutfit.objects.filter(user_id__in=following_subquery, visibility='public')
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
            liked_ids = set(
                OutfitLike.objects.filter(
                    user=request.user,
                    outfit_id__in=page_ids
                ).values_list('outfit_id', flat=True)
            )
            context = super().get_serializer_context()
            context['liked_outfit_ids'] = liked_ids
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        context = super().get_serializer_context()
        if request.user.is_authenticated:
            context['liked_outfit_ids'] = set(
                OutfitLike.objects.filter(user=request.user, outfit_id__in=[o.id for o in queryset]).values_list('outfit_id', flat=True)
            )
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)



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

        from social.your_day import get_live_weather, suggest_daily_outfit
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
        following_subquery = UserFollow.objects.filter(follower=user).values('following_id')

        qs = (
            TodayOutfit.objects.filter(visibility='public')
            .exclude(user_id__in=following_subquery)
            .exclude(user=user)
            .select_related('user')
            .prefetch_related('tagged_items', 'images')
            .annotate(_likes_count=Count('likes', distinct=True))
        )

        if category == 'adjacent':
            if hasattr(user, 'preferences') and user.preferences.style_match:
                styles = user.preferences.style_match
                style_q = Q()
                for s in styles:
                    style_q |= Q(user__preferences__style_match__icontains=s) | Q(caption__icontains=s)
                return qs.filter(style_q).order_by('-_likes_count', '-created_at')
            return qs.order_by('-_likes_count', '-created_at')

        elif category in ('minimalist', 'streetwear', 'classic', 'chic', 'casual', 'formal', 'bohemian', 'sporty'):
            cat_q = (
                Q(style_category__iexact=category) |
                Q(caption__icontains=category) |
                Q(user__preferences__style_match__icontains=category)
            )
            return qs.filter(cat_q).order_by('-_likes_count', '-created_at')

        return qs.order_by('-_likes_count', '-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [o.id for o in page]
            liked_ids = set(
                OutfitLike.objects.filter(
                    user=request.user,
                    outfit_id__in=page_ids
                ).values_list('outfit_id', flat=True)
            )
            context = super().get_serializer_context()
            context['liked_outfit_ids'] = liked_ids
            serializer = self.get_serializer(page, many=True, context=context)
            response = self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            response = Response(serializer.data)

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


