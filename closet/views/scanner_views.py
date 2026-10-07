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
from users.throttling import AIScanUserRateThrottle

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
    throttle_classes = [AIScanUserRateThrottle]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # Enforce explicit user consent server-side (GDPR Art. 7, Spec §5.5)
        from users.utils.common_utils import has_user_consent
        if not has_user_consent(request.user, kind='photo_ai_processing'):
            return Response({
                'success': False,
                'error_code': 'consent_required',
                'message': 'Explicit consent for photo and AI styling processing is required before using the AI closet scanner.',
                'consent_type': 'photo_ai_processing',
                'required_version': '1.0',
                'errors': {'consent': ['Photo and AI styling processing consent required.']}
            }, status=status.HTTP_403_FORBIDDEN)

        image_file = request.FILES.get('image') or request.FILES.get('file')
        if not image_file:
            return Response({
                'success': False,
                'message': 'No image file provided. Please capture or upload a cloth image.',
                'errors': {'image': ['Image file is required for AI scanning.']}
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate image format and integrity
        try:
            validate_image_file(image_file, max_mb=30)
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Invalid image file.',
                'errors': {'image': [str(e)]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # Run AI Scanner (protected by killswitch, rate limits, gate, and user-scoped cache)
        try:
            from closet.ai_scanner.scanner import scan_clothing_image
            scanned_data = scan_clothing_image(image_file, request=request, user=request.user)
        except TimeoutError as e:
            logger.warning(f"AI Scan 503 TimeoutError under high traffic: {e}")
            return Response({
                'success': False,
                'message': 'AI scanning service is currently experiencing very high demand. Please try again in a few moments.',
                'errors': {'server': ['AI scanning service queue timeout. Please retry in a few moments.']}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
        except Exception as e:
            from closet.exceptions import AIServiceUnavailableError, AIDailyLimitExceededError, AIImageValidationError
            from closet.ai.safety import AISafetyBlockedError, AISafetyError
            if isinstance(e, AISafetyBlockedError):
                return Response({
                    'success': False,
                    'error_code': 'nsfw_blocked',
                    'message': str(e),
                    'errors': {'safety': ['Uploaded image violates content safety guidelines.']}
                }, status=status.HTTP_400_BAD_REQUEST)
            if isinstance(e, AISafetyError):
                return Response({
                    'success': False,
                    'error_code': 'safety_service_unavailable',
                    'message': str(e),
                    'errors': {'safety': [str(e)]}
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
            if isinstance(e, AIServiceUnavailableError):
                return Response({
                    'success': False,
                    'message': str(e),
                    'errors': {'server': [str(e)]}
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
            if isinstance(e, AIDailyLimitExceededError):
                return Response({
                    'success': False,
                    'message': str(e),
                    'errors': {'quota': [str(e)]}
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if isinstance(e, AIImageValidationError):
                return Response({
                    'success': False,
                    'message': 'Invalid garment image.',
                    'errors': {'image': [str(e)]}
                }, status=status.HTTP_400_BAD_REQUEST)

            logger.error("Failed to scan garment image", exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to scan garment image due to an internal processing error. Please try again with a clear photo.',
                'errors': {'server': ['Internal image processing error.']}
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
            from rewards.models import RewardPointTransaction
            from django.conf import settings
            from django.utils import timezone
            from django.db import models
            from closet.models import FitCheck

            fit_check_obj = None
            if scanned_data.get('fit_check_id'):
                fit_check_obj = FitCheck.objects.filter(id=scanned_data['fit_check_id']).first()

            # Deduplication: Re-wear existing item if identical photo was already scanned by this user (C-07)
            if scanned_data.get('is_duplicate') and scanned_data.get('existing_item_id'):
                existing_id = scanned_data['existing_item_id']
                ClosetItem.objects.filter(id=existing_id, user=request.user).update(
                    times_worn=models.F('times_worn') + 1,
                    last_worn_at=timezone.now()
                )
                existing_item = ClosetItem.objects.get(id=existing_id, user=request.user)
                serializer = ClosetItemSerializer(existing_item, context={'request': request})
                return Response({
                    'success': True,
                    'message': f"Item recognized in your digital closet! Updated wear count for '{existing_item.name}' to {existing_item.times_worn}.",
                    'data': {
                        'item': serializer.data,
                        'is_duplicate': True,
                        'style_vibe': scanned_data.get('style_vibe'),
                        'visual_match_score': scanned_data.get('visual_match_score'),
                    }
                }, status=status.HTTP_200_OK)

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
                        fit_check=fit_check_obj,
                        name=piece.get('name', 'Wardrobe Essential'),
                        category=piece.get('category', 'top'),
                        color=piece.get('color', 'Neutral'),
                        brand=piece.get('brand', 'N/A'),
                        price=piece_price,
                        currency='EUR',
                        style_vibe=piece.get('style_vibe', ''),
                        source='scan',
                        photo_sha256=scanned_data.get('photo_sha256', ''),
                        image=scanned_data.get('saved_image_path', '')
                    )
                    # Check daily points award limit to prevent exploit (C-07)
                    daily_awards = RewardPointTransaction.objects.filter(
                        user=request.user,
                        action_type='add_closet_item',
                        created_at__date=timezone.now().date()
                    ).count()
                    if daily_awards < getattr(settings, 'MYC_CLOSET_ITEM_POINTS_DAILY_LIMIT', 10):
                        try:
                            award_points(
                                user=request.user,
                                action_type='add_closet_item',
                                description=f"Auto-scanned & added '{piece_item.name}' to closet",
                                reference_id=str(piece_item.id)
                            )
                        except Exception as e:
                            logger.warning(f"Error awarding points: {e}")
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
                fit_check=fit_check_obj,
                name=scanned_data.get('name', 'Wardrobe Essential'),
                category=scanned_data.get('category', 'top'),
                color=scanned_data.get('color', 'Neutral'),
                brand=scanned_data.get('brand', 'N/A'),
                price=item_price,
                currency='EUR',
                style_vibe=scanned_data.get('style_vibe', ''),
                source='scan',
                photo_sha256=scanned_data.get('photo_sha256', ''),
                image=scanned_data.get('saved_image_path', '')
            )

            # Check daily points award limit (C-07)
            daily_awards = RewardPointTransaction.objects.filter(
                user=request.user,
                action_type='add_closet_item',
                created_at__date=timezone.now().date()
            ).count()
            if daily_awards < getattr(settings, 'MYC_CLOSET_ITEM_POINTS_DAILY_LIMIT', 10):
                try:
                    award_points(
                        user=request.user,
                        action_type='add_closet_item',
                        description=f"Auto-scanned & added '{item.name}' to closet",
                        reference_id=str(item.id)
                    )
                except Exception as e:
                    logger.warning(f"Error awarding points: {e}")

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

