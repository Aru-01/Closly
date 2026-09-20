import logging
from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db import models
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

from .models import ClosetItem
from .serializers import ClosetItemSerializer
from users.validators import validate_image_file
from .ai_scanner import scan_clothing_image

class ClosetItemListCreateView(generics.ListCreateAPIView):
    """
    API endpoint to list and add items in the user's closet.
    
    GET /api/closet/items/ - List all user's clothes
    POST /api/closet/items/ - Add a new item to closet
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = ClosetItemSerializer

    def get_queryset(self):
        queryset = ClosetItem.objects.filter(user=self.request.user)
        category = self.request.query_params.get('category')
        color = self.request.query_params.get('color')
        brand = self.request.query_params.get('brand')

        if category:
            queryset = queryset.filter(category=category)
        if color:
            queryset = queryset.filter(color__icontains=color)
        if brand:
            queryset = queryset.filter(brand__icontains=brand)

        return queryset

    def perform_create(self, serializer):
        item = serializer.save(user=self.request.user)
        try:
            from rewards.services import award_points
            award_points(
                user=self.request.user,
                action_type='add_closet_item',
                description=f"Added '{item.name}' to closet",
                reference_id=str(item.id)
            )
        except Exception:
            pass

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            'success': True,
            'message': 'Closet items retrieved successfully.',
            'data': response.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            self.perform_create(serializer)
            return Response({
                'success': True,
                'message': 'Cloth item added to closet successfully.',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'success': False,
            'message': 'Failed to add item to closet.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class ClosetItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    API endpoint to view, update or delete a specific cloth item.
    
    GET /api/closet/items/<id>/
    PUT / PATCH / DELETE
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = ClosetItemSerializer

    def get_queryset(self):
        return ClosetItem.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Cloth details retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)


class WearTodayView(APIView):
    """
    API endpoint to record today's wear for a specific cloth item.
    Increments times_worn counter and updates last_worn_at.
    
    POST /api/closet/items/<id>/wear-today/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        try:
            item = ClosetItem.objects.get(pk=pk, user=request.user)
            item.times_worn += 1
            item.last_worn_at = timezone.now()
            item.save()

            serializer = ClosetItemSerializer(item, context={'request': request})
            return Response({
                'success': True,
                'message': f"Calculated today's wear for '{item.name}'. Times worn is now {item.times_worn}.",
                'data': serializer.data
            }, status=status.HTTP_200_OK)
        except ClosetItem.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Cloth item not found in your closet.'
            }, status=status.HTTP_404_NOT_FOUND)


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

    # Dynamic wardrobe health grades & titles (beyond just "Eco")
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


class ClosetScoreDashboardView(APIView):
    """
    Dedicated Closet Score Dashboard API.
    Returns:
    - closet_score: e.g. 74/100
    - category: "Above Average" (or "Excellent", "Good", "Needs Attention")
    - cost_wear: e.g. 2.38
    - closet_points: available points from rewards
    - achieve_rank: current tier from rewards (Bronze, Silver, Gold, Platinum, Diamond)
    - all_pieces: count
    - ghost_pieces: count
    - wardrobe_audit: { "grade": "B+", "title": "Mindful Minimalist", "badge": "B+ Mindful Minimalist", "active_pieces": 38 }
    - style_dna: { "minimal": 72, "classic": 69, "relaxed": 88, ... }
    
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
        # - Utilization rate (0 - 40 pts)
        util_pts = (analytics['utilization_rate'] / 100.0) * 40.0
        # - Cost per wear efficiency (0 - 30 pts)
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
        # - Look sharing activity (0 - 20 pts)
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
        # - Category completeness (0 - 10 pts)
        cat_count = len(set(it.category for it in items))
        cat_pts = min(10.0, cat_count * 2.5)

        raw_score = util_pts + cpw_pts + look_pts + cat_pts
        closet_score = int(round(raw_score))
        closet_score = max(25, min(99, closet_score))

        # Score category
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

        # 4. Style DNA percentages
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


class ClosetAuditView(APIView):
    """
    API endpoint for wardrobe audit & environmental impact analysis.
    Returns:
    - active_pieces
    - ghost_pieces
    - list_of_most_worn (5 items sorted by per_wear_cost in increasing order)
    - list_of_ghost_pieces (5 items sorted by price in descending order)
    - environmental_and_space_impact (wasted_carbon_kg, co2_saved_kg, wasted_investment_cost, space_waste_percentage)
    - wardrobe_status (grade, title, badge, feedback)
    
    GET /api/closet/audit/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        items = list(ClosetItem.objects.filter(user=user))
        analytics = get_wardrobe_analytics(user, items)

        # 1. 5 Most worn items ordered by per_wear_cost in INCREASING order ($2, $5, etc.)
        worn_items_list = [it for it in items if it.times_worn > 0]
        worn_items_sorted = sorted(worn_items_list, key=lambda x: x.per_wear_cost)[:5]

        # 2. 5 Ghost pieces ordered by price in DESCENDING order (highest neglected investments)
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


class ClosetAIScanView(APIView):
    """
    AI Garment Scanner endpoint.
    Scans a garment image taken via camera or selected from device gallery.
    
    POST /api/closet/ai-scan/ (multipart/form-data with 'image')
    Query Params:
      ?auto_save=true (optional, creates ClosetItem directly and awards points)
    
    Returns pre-filled attributes:
    - name, category, color, brand, price, style_vibe, confidence, image_url
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        image_file = request.FILES.get('image') or request.FILES.get('file')
        if not image_file:
            return Response({
                'success': False,
                'message': 'No image file provided. Please capture or upload a cloth image.',
                'errors': {'image': ['Image file is required for AI scanning.']}
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate image file
        try:
            validate_image_file(image_file, max_mb=30)
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Invalid image file.',
                'errors': {'image': [str(e)]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # Run AI Scanner (protected by concurrency semaphore and cache)
        try:
            scanned_data = scan_clothing_image(image_file, request=request)
        except TimeoutError as e:
            logger.error(f"AI Scan 503 TimeoutError under high traffic: {e}")
            return Response({
                'success': False,
                'message': str(e),
                'errors': {'server': ['AI scanning service is currently experiencing very high demand. Please try again in a few moments.']}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
        except Exception as e:
            return Response({
                'success': False,
                'message': f"Failed to scan garment image: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Check if the uploaded image contains an actual wearable clothing item
        if not scanned_data.get('is_garment', True):
            return Response({
                'success': False,
                'is_garment': False,
                'message': scanned_data.get('message') or "The uploaded image does not appear to be a clothing item. Please capture or upload a clear photo of a garment.",
                'notes': scanned_data.get('notes', ''),
            }, status=status.HTTP_200_OK)

        # Check for auto_save
        auto_save_param = request.query_params.get('auto_save', '').lower()
        save_all_param = request.query_params.get('save_all', '').lower() in ('true', '1', 'yes')
        is_save_all = (auto_save_param == 'all') or save_all_param
        auto_save = auto_save_param in ('true', '1', 'yes', 'all') or save_all_param

        if auto_save:
            from rewards.services import award_points

            if is_save_all and scanned_data.get('is_full_outfit') and scanned_data.get('detected_items'):
                # Save all detected outfit pieces into closet
                created_items = []
                for piece in scanned_data['detected_items']:
                    piece_price = piece.get('price', 35.00)
                    try:
                        if isinstance(piece_price, str):
                            piece_price = float(piece_price.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip())
                        else:
                            piece_price = float(piece_price)
                    except (ValueError, TypeError):
                        piece_price = 35.00

                    piece_item = ClosetItem.objects.create(
                        user=request.user,
                        name=piece.get('name', 'Wardrobe Essential'),
                        category=piece.get('category', 'top'),
                        color=piece.get('color', 'Neutral'),
                        brand=piece.get('brand', 'N/A'),
                        price=piece_price,
                        image=scanned_data.get('saved_image_path', '')
                    )
                    try:
                        award_points(
                            user=request.user,
                            action_type='add_closet_item',
                            description=f"Auto-scanned & added '{piece_item.name}' to closet",
                            reference_id=str(piece_item.id)
                        )
                    except Exception:
                        pass
                    created_items.append(piece_item)

                serializer = ClosetItemSerializer(created_items, many=True, context={'request': request})
                return Response({
                    'success': True,
                    'message': f"Full outfit look scanned and all {len(created_items)} pieces saved to closet.",
                    'data': {
                        'saved_pieces_count': len(created_items),
                        'items': serializer.data,
                        'style_vibe': scanned_data.get('style_vibe'),
                        'visual_match_score': scanned_data.get('visual_match_score'),
                    }
                }, status=status.HTTP_201_CREATED)

            # Single item auto-save
            item_price = scanned_data.get('price', 35.00)
            try:
                if isinstance(item_price, str):
                    item_price = float(item_price.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip())
                else:
                    item_price = float(item_price)
            except (ValueError, TypeError):
                item_price = 35.00

            item = ClosetItem.objects.create(
                user=request.user,
                name=scanned_data.get('name', 'Wardrobe Essential'),
                category=scanned_data.get('category', 'top'),
                color=scanned_data.get('color', 'Neutral'),
                brand=scanned_data.get('brand', 'N/A'),
                price=item_price,
                image=scanned_data.get('saved_image_path', '')
            )
            try:
                award_points(
                    user=request.user,
                    action_type='add_closet_item',
                    description=f"Auto-scanned & added '{item.name}' to closet",
                    reference_id=str(item.id)
                )
            except Exception:
                pass

            serializer = ClosetItemSerializer(item, context={'request': request})
            return Response({
                'success': True,
                'message': f"Garment scanned and automatically saved to closet as '{item.name}'.",
                'data': {
                    'item': serializer.data,
                    'style_vibe': scanned_data.get('style_vibe'),
                    'visual_match_score': scanned_data.get('visual_match_score'),
                }
            }, status=status.HTTP_201_CREATED)

        # Standard Pre-Fill Response for mobile app form (clean client data)
        client_data = {k: v for k, v in scanned_data.items() if k not in ('saved_image_path', 'is_garment')}

        return Response({
            'success': True,
            'message': 'Garment image scanned successfully. Pre-fill data generated.',
            'data': client_data
        }, status=status.HTTP_200_OK)


