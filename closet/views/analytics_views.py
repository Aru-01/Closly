import logging
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from closet.models import ClosetItem
from closet.serializers import ClosetItemSerializer

logger = logging.getLogger(__name__)


from closet.services.analytics_services import get_wardrobe_analytics


@extend_schema(
    tags=["AI Wardrobe Scanner & Vision"],
    summary="Closet Score & Health Dashboard",
    description="Calculates comprehensive closet sustainability score (0-100), cost-per-wear metrics, style DNA breakdown, and achievement rank.",
    responses={
        200: OpenApiResponse(description="Closet score metrics and style breakdown")
    }
)
class ClosetScoreDashboardView(APIView):
    """
    Dedicated Closet Score Dashboard API.
    Returns:
    - closet_score: e.g. 74/100 (0/100 for brand new users with empty wardrobe)
    - category: "Above Average" / "Starting Out"
    - cost_wear: average cost per wear
    - closet_points: available points from rewards
    - achieve_rank: current tier from rewards
    - all_pieces, ghost_pieces, wardrobe_audit, style_dna
    
    GET /api/closet/score/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        items = list(ClosetItem.objects.filter(user=user))
        analytics = get_wardrobe_analytics(user, items)

        from rewards.models import UserRewardProfile
        reward_profile, _ = UserRewardProfile.objects.get_or_create(user=user)
        closet_pts = reward_profile.available_points
        achieve_rank = reward_profile.current_tier

        pref = getattr(user, 'preferences', None)
        styles = pref.style_match if pref and pref.style_match else []
        vibes = pref.what_do_you_dress_for if pref and pref.what_do_you_dress_for else []

        # Dynamic Style DNA derived from actual wardrobe items and style preferences (C-13)
        if not items:
            style_dna = {
                'minimal': 10 if 'minimalist' in styles else 0,
                'classic': 10 if 'classic' in styles else 0,
                'relaxed': 10 if ('weekend' in vibes or 'home-lounge' in vibes) else 0,
                'streetwear': 10 if 'streetwear' in styles else 0,
                'sporty': 10 if ('sporty' in styles or 'active-gym' in vibes) else 0,
            }
        else:
            total_it = len(items)
            minimal_count = sum(1 for it in items if (it.color or '').lower() in ('black', 'white', 'grey', 'gray', 'beige', 'navy blue', 'neutral') or 'minimal' in (it.style_vibe or '').lower())
            classic_count = sum(1 for it in items if it.category in ('top', 'bottom', 'dresses_outerwear') or 'classic' in (it.style_vibe or '').lower() or 'elevated' in (it.style_vibe or '').lower())
            relaxed_count = sum(1 for it in items if 'casual' in (it.style_vibe or '').lower() or 'relaxed' in (it.style_vibe or '').lower() or it.category in ('top', 'bottom'))
            street_count = sum(1 for it in items if 'streetwear' in (it.style_vibe or '').lower() or it.category in ('shoes', 'accessories'))
            sporty_count = sum(1 for it in items if 'sport' in (it.style_vibe or '').lower() or 'athletic' in (it.style_vibe or '').lower() or it.category == 'shoes')

            style_dna = {
                'minimal': min(100, int(round((minimal_count / total_it) * 80 + (15 if 'minimalist' in styles else 5)))),
                'classic': min(100, int(round((classic_count / total_it) * 80 + (15 if 'classic' in styles else 5)))),
                'relaxed': min(100, int(round((relaxed_count / total_it) * 80 + (15 if ('weekend' in vibes or 'home-lounge' in vibes) else 5)))),
                'streetwear': min(100, int(round((street_count / total_it) * 80 + (15 if 'streetwear' in styles else 5)))),
                'sporty': min(100, int(round((sporty_count / total_it) * 80 + (15 if ('sporty' in styles or 'active-gym' in vibes) else 5)))),
            }


        # 0 pieces in wardrobe: return realistic 0 score with guidance
        if not items:
            return Response({
                'success': True,
                'message': 'Closet score dashboard metrics calculated successfully.',
                'data': {
                    'closet_score': "0/100",
                    'score_num': 0,
                    'category': "Starting Out",
                    'cost_wear': 0.0,
                    'closet_points': closet_pts,
                    'achieve_rank': achieve_rank,
                    'all_pieces': 0,
                    'ghost_pieces': 0,
                    'wardrobe_audit': {
                        'grade': 'N/A',
                        'title': 'Empty Closet',
                        'badge': 'Starting Out',
                        'active_pieces': 0,
                        'feedback': 'Your wardrobe is currently empty. Add clothes to start tracking rotation, sustainability, and efficiency.'
                    },
                    'style_dna': style_dna
                }
            }, status=status.HTTP_200_OK)

        # 1. Cost per wear (average across worn pieces)
        worn_items = [it for it in items if it.times_worn > 0]
        if worn_items:
            avg_cpw = round(sum(it.per_wear_cost for it in worn_items) / len(worn_items), 2)
        else:
            avg_cpw = round(float(sum((it.price or 0.0) for it in items) / len(items)), 2)

        # 2. Closet Score Calculation (0 - 100)
        # Utilization points (up to 40 pts)
        util_pts = (analytics['utilization_rate'] / 100.0) * 40.0

        # Cost per wear efficiency points (up to 30 pts)
        if worn_items:
            if avg_cpw <= 3.0:
                cpw_pts = 30.0
            elif avg_cpw <= 8.0:
                cpw_pts = 24.0
            elif avg_cpw <= 15.0:
                cpw_pts = 18.0
            elif avg_cpw <= 30.0:
                cpw_pts = 12.0
            else:
                cpw_pts = 6.0
        else:
            cpw_pts = 6.0

        # Looks activity points (up to 20 pts)
        from social.models import TodayOutfit
        thirty_days_ago = timezone.now() - timedelta(days=30)
        looks_count = TodayOutfit.objects.filter(user=user, created_at__gte=thirty_days_ago).count()
        if looks_count >= 5:
            look_pts = 20.0
        elif looks_count >= 3:
            look_pts = 16.0
        elif looks_count >= 1:
            look_pts = 10.0
        else:
            look_pts = 0.0

        # Category diversity points (up to 10 pts)
        cat_count = len(set(it.category for it in items))
        cat_pts = min(10.0, cat_count * 2.5)

        raw_score = util_pts + cpw_pts + look_pts + cat_pts
        closet_score = int(round(raw_score))
        closet_score = max(0, min(100, closet_score))

        if closet_score >= 85:
            category = "Excellent"
        elif closet_score >= 70:
            category = "Above Average"
        elif closet_score >= 50:
            category = "Average"
        elif closet_score >= 30:
            category = "Needs Attention"
        else:
            category = "Starting Out"

        return Response({
            'success': True,
            'message': 'Closet score dashboard metrics calculated successfully.',
            'data': {
                'closet_score': f"{closet_score}/100",
                'score_num': closet_score,
                'category': category,
                'cost_wear': avg_cpw,
                'closet_points': closet_pts,
                'achieve_rank': achieve_rank,
                'all_pieces': analytics['total_pieces'],
                'ghost_pieces': analytics['ghost_pieces'],
                'wardrobe_audit': {
                    'grade': analytics['status']['grade'],
                    'title': analytics['status']['title'],
                    'badge': analytics['status']['badge'],
                    'active_pieces': analytics['active_pieces'],
                    'feedback': analytics['status']['feedback']
                },
                'style_dna': style_dna
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["AI Wardrobe Scanner & Vision"],
    summary="Wardrobe Audit & Carbon Impact",
    description="Generates wardrobe audit statistics: active pieces, ghost pieces, top 5 most worn pieces, top 5 dormant pieces, and carbon/investment waste analysis.",
    responses={
        200: OpenApiResponse(description="Wardrobe audit details and environmental impact")
    }
)
class ClosetAuditView(APIView):
    """
    API endpoint for wardrobe audit & environmental impact analysis.
    
    GET /api/closet/audit/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        items = list(ClosetItem.objects.filter(user=user))
        analytics = get_wardrobe_analytics(user, items)

        worn_items_list = [it for it in items if it.times_worn > 0]
        worn_items_sorted = sorted(worn_items_list, key=lambda x: x.per_wear_cost)[:5]
        ghost_items_sorted = sorted(analytics['ghost_items'], key=lambda x: (x.price or 0.0), reverse=True)[:5]

        return Response({
            'success': True,
            'message': 'Wardrobe audit and environmental impact analysis generated successfully.',
            'data': {
                'total_pieces': analytics['total_pieces'],
                'total_items': analytics['total_pieces'],
                'active_pieces': analytics['active_pieces'],
                'ghost_pieces': analytics['ghost_pieces'],
                'utilization_rate': analytics['utilization_rate'],
                'wardrobe_status': analytics['status'],
                'environmental_and_space_impact': analytics['impact'],
                'list_of_most_worn': ClosetItemSerializer(worn_items_sorted, many=True, context={'request': request}).data,
                'list_of_ghost_pieces': ClosetItemSerializer(ghost_items_sorted, many=True, context={'request': request}).data
            }
        }, status=status.HTTP_200_OK)
