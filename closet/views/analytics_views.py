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


def get_wardrobe_analytics(user, items):
    items_list = list(items) if not isinstance(items, list) else items
    total_items = len(items_list)
    now = timezone.now()
    fifteen_days_ago = now - timedelta(days=15)

    # Ghost pieces: never worn (times_worn == 0) OR not worn in the last 15 days
    ghost_items = [
        it for it in items_list
        if it.times_worn == 0 or it.last_worn_at is None or it.last_worn_at < fifteen_days_ago
    ]
    ghost_count = len(ghost_items)
    active_count = max(0, total_items - ghost_count)

    utilization_rate = (active_count / total_items * 100) if total_items > 0 else 100.0

    # Dynamic wardrobe health grades & titles
    if utilization_rate >= 85:
        grade = "A+"
        title = "Conscious Curator"
        badge = "A+ Conscious Curator"
        feedback = "Masterclass in wardrobe rotation! Zero waste, maximum style efficiency."
    elif utilization_rate >= 70:
        grade = "A"
        title = "Sustainable Trendsetter"
        badge = "A Sustainable Trendsetter"
        feedback = "High efficiency wardrobe. Your pieces are in consistent, healthy rotation."
    elif utilization_rate >= 55:
        grade = "B+"
        title = "Mindful Minimalist"
        badge = "B+ Mindful Minimalist"
        feedback = "Solid active rotation on core pieces, but several ghost items need styling attention."
    elif utilization_rate >= 40:
        grade = "B"
        title = "Active Balancer"
        badge = "B Active Balancer"
        feedback = "Balanced rotation, but approximately half your closet is sitting idle."
    elif utilization_rate >= 25:
        grade = "C+"
        title = "Closet in Transition"
        badge = "C+ Closet in Transition"
        feedback = "Multiple dormant pieces taking up storage space. Consider restyling or clearing."
    else:
        grade = "C"
        title = "Ghost Heavy"
        badge = "C Ghost Heavy"
        feedback = "Majority of wardrobe is unworn. High dormant carbon and unused investment."

    # Environmental & Space Waste Impact of Ghost Pieces
    wasted_carbon_kg = round(ghost_count * 12.5, 2)
    wasted_investment = float(sum((it.price or 0.0) for it in ghost_items))
    space_waste_pct = round((ghost_count / total_items * 100), 1) if total_items > 0 else 0.0
    co2_saved = round(sum(max(0, it.times_worn - 1) for it in items_list) * 0.85, 2)

    return {
        'total_pieces': total_items,
        'active_pieces': active_count,
        'ghost_pieces': ghost_count,
        'utilization_rate': round(utilization_rate, 1),
        'status': {
            'grade': grade,
            'title': title,
            'badge': badge,
            'feedback': feedback
        },
        'impact': {
            'wasted_carbon_kg': wasted_carbon_kg,
            'wasted_investment_cost': round(wasted_investment, 2),
            'space_waste_percentage': space_waste_pct,
            'co2_saved_kg': co2_saved,
            'summary': f"{ghost_count} unworn pieces represent {wasted_carbon_kg} kg of dormant CO2 and ${wasted_investment:,.2f} in idle closet space."
        },
        'ghost_items': ghost_items,
        'ghost_items_qs': items if hasattr(items, 'filter') else ClosetItem.objects.filter(user=user, id__in=[it.id for it in ghost_items]),
        'items_list': items_list
    }


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
    - closet_score: e.g. 74/100
    - category: "Above Average"
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

        # 1. Cost per wear (average across worn pieces)
        worn_items = [it for it in items if it.times_worn > 0]
        if worn_items:
            avg_cpw = round(sum(it.per_wear_cost for it in worn_items) / len(worn_items), 2)
        elif items:
            avg_cpw = round(float(sum((it.price or 0.0) for it in items) / len(items)), 2)
        else:
            avg_cpw = 0.0

        # 2. Closet Points & Achievement Rank
        from rewards.models import UserRewardProfile
        reward_profile, _ = UserRewardProfile.objects.get_or_create(user=user)
        closet_pts = reward_profile.available_points
        achieve_rank = reward_profile.current_tier

        # 3. Closet Score Calculation (0 - 100)
        util_pts = (analytics['utilization_rate'] / 100.0) * 40.0
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

        from social.models import TodayOutfit
        thirty_days_ago = timezone.now() - timedelta(days=30)
        looks_count = TodayOutfit.objects.filter(user=user, created_at__gte=thirty_days_ago).count()
        if looks_count >= 5:
            look_pts = 20.0
        elif looks_count >= 3:
            look_pts = 16.0
        elif looks_count >= 1:
            look_pts = 12.0
        else:
            look_pts = 6.0

        cat_count = len(set(it.category for it in items))
        cat_pts = min(10.0, cat_count * 2.5)

        raw_score = util_pts + cpw_pts + look_pts + cat_pts
        closet_score = int(round(raw_score))
        closet_score = max(25, min(99, closet_score))

        if closet_score >= 85:
            category = "Excellent"
        elif closet_score >= 70:
            category = "Above Average"
        elif closet_score >= 55:
            category = "Average"
        elif closet_score >= 40:
            category = "Needs Attention"
        else:
            category = "Starting Out"

        pref = getattr(user, 'preferences', None)
        styles = pref.style_match if pref and pref.style_match else []
        vibes = pref.what_do_you_dress_for if pref and pref.what_do_you_dress_for else []

        style_dna = {
            'minimal': 72 if 'minimalist' in styles else 62,
            'classic': 69 if 'classic' in styles else 58,
            'relaxed': 88 if ('weekend' in vibes or 'home-lounge' in vibes) else 74,
            'streetwear': 65 if 'streetwear' in styles else 52,
            'sporty': 68 if 'sporty' in styles or 'active-gym' in vibes else 48,
        }

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
