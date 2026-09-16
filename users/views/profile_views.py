import logging
from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.authentication import FirebaseAuthentication
from users.serializers import (
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    LanguagePreferenceSerializer,
)
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]
    """
    API endpoint to get and update user profile
    
    GET /api/users/profile/ - Get user profile
    PUT /api/users/profile/ - Update full profile
    PATCH /api/users/profile/ - Partial update profile
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user profile with preloaded preferences and reward profile"""
        user = User.objects.select_related('preferences', 'reward_profile').get(pk=request.user.pk)
        serializer = UserProfileSerializer(user, context={'request': request})
        
        return standard_response(
            success=True,
            message="Profile retrieved successfully",
            data=serializer.data,
            status_code=status.HTTP_200_OK
        )
    
    def put(self, request):
        """Update full user profile"""
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            
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
        """Partial update user profile"""
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            
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



class SetLanguageView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]
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
        "height_cm": 165,
        "weight_kg": 60,
        "chest": "36 inches",
        "waist": "30 inches",
        "hip": "38 inches",
        "body_size": "m",
        "shoe_size": "UK 8",

        "skin_tone": "#F0B27A",
        "color_palette": "neutral_minimalist",
        "clothing_categories": {
            "tops": ["shirts", "hoodies"],
            "shoes": ["sneakers", "boots"]
        },
        "preferred_brands": ["zara", "nike", "uniqlo"]
    }
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]

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


class ShareProfileAPIView(APIView):
    """
    API endpoint to retrieve user's shareable profile link, referral code, and share text.
    
    GET /api/users/profile/share/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, FirebaseAuthentication]

    def get(self, request):
        user = request.user
        if not user.referral_code:
            user.save()

        share_url = request.build_absolute_uri(f"/u/{user.id}/")
        referral_code = user.referral_code
        share_text = f"Check out my fashion closet and daily styles on Closly! Join using my link: {share_url}?ref={referral_code}"

        return Response({
            'success': True,
            'message': 'Share profile data retrieved successfully.',
            'data': {
                'share_url': share_url,
                'referral_code': referral_code,
                'share_text': share_text,
                'deep_link': f"closly://user/{user.id}?ref={referral_code}",
            }
        }, status=status.HTTP_200_OK)


class PublicProfileWebView(APIView):
    """
    Public web landing page for a shared profile.
    Renders mobile-first luxury profile view with deep-link into Closly app.
    
    GET /u/<uuid:user_id>/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, user_id):
        try:
            profile_user = User.objects.filter(pk=user_id).first()
        except (ValueError, TypeError):
            profile_user = None

        if not profile_user:
            from django.http import Http404
            raise Http404("User profile not found.")
        
        reward_profile = getattr(profile_user, 'reward_profile', None)
        tier = reward_profile.current_tier if reward_profile else 'Bronze'
        
        closet_count = profile_user.closet_items.count()
        outfit_count = profile_user.today_outfits.filter(visibility='public').count()
        followers_count = profile_user.followers_set.count()
        recent_outfits = profile_user.today_outfits.filter(visibility='public')[:6]

        context = {
            'profile_user': profile_user,
            'tier': tier,
            'closet_count': closet_count,
            'outfit_count': outfit_count,
            'followers_count': followers_count,
            'recent_outfits': recent_outfits,
        }
        return render(request, 'users/public_profile.html', context)
