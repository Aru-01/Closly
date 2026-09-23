import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from closet.models import ClosetItem
from closet.serializers import ClosetItemSerializer
from closet.ai_scanner import scan_clothing_image
from users.validators import validate_image_file
from users.throttling import AIScanUserRateThrottle, AIScanAnonRateThrottle

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["AI Wardrobe Scanner & Vision"],
    summary="AI Garment Scanner (Camera & Upload)",
    description=(
        "Scans a garment image using computer vision and AI. Automatically extracts category, "
        "dominant fashion color, style vibe, and price estimation.\n\n"
        "Set query parameter `?auto_save=true` to automatically create a new ClosetItem and earn reward points."
    ),
    parameters=[
        OpenApiParameter('auto_save', str, description="Set to 'true' or 'all' to automatically persist detected garments to the user closet"),
        OpenApiParameter('save_all', bool, description="Set to true to save all multi-piece outfit items"),
    ],
    responses={
        200: OpenApiResponse(description="Pre-filled garment metadata returned successfully"),
        201: OpenApiResponse(description="Garment scanned and auto-saved to digital closet"),
        400: OpenApiResponse(description="Invalid or missing image file"),
        503: OpenApiResponse(description="AI scanning service high traffic retry header"),
    }
)
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
    throttle_classes = [AIScanUserRateThrottle, AIScanAnonRateThrottle]
    parser_classes = [MultiPartParser, FormParser]

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
            import closet.views
            scanned_data = closet.views.scan_clothing_image(image_file, request=request)
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
                    except Exception as e:
                        logger.warning(f"Error awarding points for auto-scanned outfit item: {e}")
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
            except Exception as e:
                logger.warning(f"Error awarding points for auto-scanned single item: {e}")

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

        client_data = {k: v for k, v in scanned_data.items() if k not in ('saved_image_path', 'is_garment')}

        return Response({
            'success': True,
            'message': 'Garment image scanned successfully. Pre-fill data generated.',
            'data': client_data
        }, status=status.HTTP_200_OK)
