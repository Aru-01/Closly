import logging
from django.shortcuts import render
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.serializers import (
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    LanguagePreferenceSerializer,
)
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

@extend_schema(
    tags=["User Profile & Preferences"],
    summary="User Profile (Get / Update)",
    description="Retrieve or update authenticated user profile details, bio, location, and avatar.",
    responses={
        200: UserProfileSerializer,
        400: OpenApiResponse(description="Validation error"),
    }
)
class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    """
    API endpoint to get and update user profile
    
    GET /api/users/profile/ - Get user profile
    PUT /api/users/profile/ - Update full profile
    PATCH /api/users/profile/ - Partial update profile
    """
    
    def get(self, request):
        """Get user profile with preloaded preferences and reward profile"""
        from users.utils import set_user_online
        set_user_online(str(request.user.id))
        user = User.objects.select_related('preferences', 'reward_profile').get(pk=request.user.pk)
        serializer = UserProfileSerializer(user, context={'request': request})
        
        return standard_response(
            success=True,
            message="Profile retrieved successfully",
            data=serializer.data,
            status_code=status.HTTP_200_OK
        )
    
    def put(self, request):
        """Update full user profile with avatar file cleanup (U-30)"""
        user = request.user
        old_avatar = user.profile_picture
        serializer = UserProfileUpdateSerializer(user, data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            if old_avatar and 'profile_picture' in serializer.validated_data and old_avatar != user.profile_picture:
                try:
                    old_avatar.delete(save=False)
                except Exception as e:
                    logger.warning(f"Error removing old profile picture: {e}")
            
            # Return updated profile
            profile_serializer = UserProfileSerializer(user, context={'request': request})
            
            return standard_response(
                success=True,
                message="Profile updated successfully",
                data=profile_serializer.data,
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Profile update failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    def patch(self, request):
        """Partial update user profile with avatar file cleanup (U-30)"""
        user = request.user
        old_avatar = user.profile_picture
        serializer = UserProfileUpdateSerializer(user, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            if old_avatar and 'profile_picture' in serializer.validated_data and old_avatar != user.profile_picture:
                try:
                    old_avatar.delete(save=False)
                except Exception as e:
                    logger.warning(f"Error removing old profile picture: {e}")
            
            # Return updated profile
            profile_serializer = UserProfileSerializer(user, context={'request': request})
            
            return standard_response(
                success=True,
                message="Profile updated successfully",
                data=profile_serializer.data,
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Profile update failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )



@extend_schema(
    tags=["User Profile & Preferences"],
    summary="Set Preferred Language",
    description="Updates user interface language preference (e.g. 'en', 'fr', 'es', 'de').",
    request=LanguagePreferenceSerializer,
    responses={
        200: OpenApiResponse(description="Language preference updated successfully"),
        400: OpenApiResponse(description="Invalid language code"),
    }
)
class SetLanguageView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = LanguagePreferenceSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            language = serializer.validated_data['language']
            user = request.user
            user.preferred_language = language
            user.save(update_fields=['preferred_language'])
            return standard_response(success=True, message="Language preference updated successfully.", data={'language': language})
        return standard_response(success=False, message="Invalid request data", errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)



# ======================================================================
# USER PREFERENCE VIEW
# ======================================================================

from users.models import UserPreference
from users.serializers import UserPreferenceSerializer


@extend_schema(
    tags=["User Profile & Preferences"],
    summary="Fashion Styling Preferences & Onboarding",
    description="Retrieve or update dynamic onboarding choices, body measurements, style match, color palette, and preferred brands.",
    responses={
        200: OpenApiResponse(description="Preferences retrieved or saved successfully"),
        400: OpenApiResponse(description="Invalid preference data"),
    }
)
class UserPreferenceView(APIView):
    """
    GET  /api/users/preferences/
        Returns the current user's preferences + all valid choice options
        so the frontend can render the onboarding UI dynamically.

    POST /api/users/preferences/
        Save/update preferences. All fields are optional — submit any
        subset. Designed to support saving one page at a time.

    Example POST body (all fields optional, submit only what you have):
    {
        "style_match": ["minimalist", "classic"],
        "body_type": "hourglass",
        "body_size": "m",
        "shoe_size": "UK 8",
        "color_palette": "neutral_minimalist",
        "clothing_categories": {
            "tops": ["shirts", "hoodies"],
            "shoes": ["sneakers", "boots"]
        },
        "preferred_brands": ["zara", "nike", "uniqlo"],
        "price_band": "mid_range",
        "gender_prefs": ["women", "unisex"],
        "clothing_sizes": ["M", "EU 38"],
        "blocked_brands": ["shein"]
    }
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(prefs)
        return Response({
            'success': True,
            'message': 'Preferences retrieved successfully.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        # partial=True means ALL fields are optional on every call
        serializer = UserPreferenceSerializer(prefs, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()

            # Invalidate feed cache upon preference change (U-21)
            from django.core.cache import cache
            cache.delete(f"user_feed_{request.user.id}")

            # Activate pending referral reward if onboarding is completed (U-09)
            if prefs.onboarding_completed:
                from rewards.services import activate_referral_reward
                activate_referral_reward(request.user)

            return Response({
                'success': True,
                'message': 'Preferences saved successfully.',
                'data': serializer.data,
            }, status=status.HTTP_200_OK)
        return Response({
            'success': False,
            'message': 'Invalid preference data.',
            'errors': serializer.errors,
        }, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        """Update onboarding preferences (full/partial update)"""
        return self.post(request)

    def patch(self, request):
        """Partial update onboarding preferences"""
        return self.post(request)


@extend_schema(
    tags=["User Profile & Preferences"],
    summary="Shareable Profile Link & Referral Code",
    description="Returns user's unique profile link, referral code, pre-composed invite text, and mobile app deep-link.",
    responses={
        200: OpenApiResponse(description="Shareable profile details and deep-links"),
    }
)
class ShareProfileAPIView(APIView):
    """
    API endpoint to retrieve user's shareable profile link, referral code, and share text.
    
    GET /api/users/profile/share/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        if not user.referral_code:
            user.save()

        # Build share handle from username (fallback to UUID), never email (U-13)
        handle = user.username or str(user.id)
        from django.conf import settings
        backend_url = (getattr(settings, "MYC_PUBLIC_BASE_URL", "") or getattr(settings, "BACKEND_URL", "")).rstrip("/")
        if not backend_url and request is not None:
            backend_url = request.build_absolute_uri('/')[:-1]
        if not backend_url:
            backend_url = "http://localhost:8000"

        scheme = getattr(settings, "MYC_DEEP_LINK_SCHEME", "closly")
        share_url = f"{backend_url}/u/{handle}/"
        referral_code = user.referral_code
        brand_name = getattr(settings, "MYC_BRAND_NAME", "Closly")
        share_text = f"Check out my fashion closet and daily styles on {brand_name}! Join using my link: {share_url}"

        return Response({
            'success': True,
            'message': 'Share profile data retrieved successfully.',
            'data': {
                'share_url': share_url,
                'referral_code': referral_code,
                'share_text': share_text,
                'deep_link': f"{scheme}://user/{handle}",
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["User Profile & Preferences"],
    summary="Public Profile Preview / Landing Page",
    description="Retrieves public profile data via JSON for API/Postman or renders web landing page with deep-link CTA into Closly app.",
    responses={
        200: OpenApiResponse(description="Public profile data retrieved or HTML page rendered"),
        404: OpenApiResponse(description="User profile not found"),
    }
)
class PublicProfileWebView(APIView):
    """
    Public landing page and API resolver for a shared profile.
    Renders mobile-first luxury profile view or returns JSON profile data.
    
    GET /u/<str:user_id>/ (UUID or unique username lookup, U-13)
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, user_id):
        import uuid
        from django.http import Http404
        profile_user = None

        # 1. Try UUID lookup
        try:
            val = uuid.UUID(str(user_id))
            profile_user = User.objects.filter(pk=val, is_active=True).first()
        except (ValueError, TypeError, AttributeError):
            pass

        # 2. Try unique case-insensitive username lookup (U-13)
        if not profile_user:
            profile_user = User.objects.filter(username__iexact=str(user_id), is_active=True).first()

        if not profile_user:
            raise Http404("User profile not found.")
        
        reward_profile = getattr(profile_user, 'reward_profile', None)
        tier = reward_profile.current_tier if reward_profile else 'Bronze'
        
        closet_count = profile_user.closet_items.count()
        outfit_count = profile_user.today_outfits.filter(visibility='public').count()
        followers_count = profile_user.followers_set.count()
        recent_outfits = profile_user.today_outfits.filter(visibility='public')[:6]

        from django.conf import settings
        scheme = getattr(settings, 'MYC_DEEP_LINK_SCHEME', 'closly')
        handle = profile_user.username or str(profile_user.id)
        deep_link = f"{scheme}://user/{handle}"

        # Content negotiation: return JSON for API clients / Postman, HTML for browsers
        accept = request.headers.get('Accept', '')
        user_agent = request.headers.get('User-Agent', '')
        is_html_browser = 'text/html' in accept or ('Mozilla' in user_agent and request.query_params.get('format') != 'json')

        if not is_html_browser or request.query_params.get('format') == 'json':
            profile_pic_url = None
            if profile_user.profile_picture:
                profile_pic_url = request.build_absolute_uri(profile_user.profile_picture.url)

            return standard_response(
                success=True,
                message="User public profile retrieved successfully.",
                data={
                    'user': {
                        'id': str(profile_user.id),
                        'name': profile_user.name,
                        'username': profile_user.username,
                        'bio': profile_user.bio,
                        'country': profile_user.country,
                        'city': profile_user.city,
                        'profile_picture': profile_pic_url,
                        'tier': tier,
                    },
                    'stats': {
                        'closet_count': closet_count,
                        'outfit_count': outfit_count,
                        'followers_count': followers_count,
                    },
                    'deep_link': deep_link,
                    'recent_outfits': [
                        {
                            'id': o.id,
                            'caption': o.caption,
                            'style_category': o.style_category,
                            'weather_tag': o.weather_tag,
                        }
                        for o in recent_outfits
                    ]
                },
                status_code=status.HTTP_200_OK,
                code="PROFILE_RETRIEVED"
            )

        context = {
            'profile_user': profile_user,
            'tier': tier,
            'closet_count': closet_count,
            'outfit_count': outfit_count,
            'followers_count': followers_count,
            'recent_outfits': recent_outfits,
            'deep_link': deep_link,
            'deep_link_scheme': scheme,
        }
        return render(request, 'users/public_profile.html', context)

# Re-export for backward compatibility
from users.views.device_views import DeviceRegistrationView


