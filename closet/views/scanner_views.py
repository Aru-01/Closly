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

        # Validate image format and integrity (P-12: standardized 10MB limit)
        try:
            validate_image_file(image_file, max_mb=10)
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Invalid image file.',
                'errors': {'image': [str(e)]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # P-05 & SPEC-RULE-01: Pure Asynchronous AI Processing via Background Worker (HTTP 202)
        from closet.ai.gateway import AIGateway
        from closet.exceptions import AIServiceUnavailableError, AIDailyLimitExceededError, AIImageValidationError
        from closet.utils import validate_and_sanitize_image, persist_sanitized_image
        from closet.models import FitCheck
        from closet.tasks import process_fit_check_task

        try:
            AIGateway.check_preconditions(request.user)
        except AIServiceUnavailableError as e:
            return Response({
                'success': False,
                'error_code': 'service_unavailable',
                'message': str(e),
                'errors': {'server': [str(e)]}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
        except AIDailyLimitExceededError as e:
            return Response({
                'success': False,
                'error_code': 'quota_exceeded',
                'message': str(e),
                'errors': {'quota': [str(e)]}
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            sanitized_bytes, photo_sha256, mime = validate_and_sanitize_image(image_file)
        except AIImageValidationError as e:
            return Response({
                'success': False,
                'error_code': 'invalid_image',
                'message': str(e),
                'errors': {'image': [str(e)]}
            }, status=status.HTTP_400_BAD_REQUEST)

        existing_item = ClosetItem.objects.filter(user=request.user, photo_sha256=photo_sha256).first()
        if existing_item:
            serializer = ClosetItemSerializer(existing_item, context={'request': request})
            return Response({
                'success': True,
                'status': 'dedupe_hit',
                'message': f"Item recognized in your digital closet! '{existing_item.name}'.",
                'data': {
                    'item': serializer.data,
                    'is_duplicate': True,
                }
            }, status=status.HTTP_200_OK)

        saved_path = persist_sanitized_image(
            sanitized_bytes,
            folder=f"fit_checks/{request.user.id}",
            prefix="scan_"
        )

        fit_check = FitCheck.objects.create(
            user=request.user,
            photo=saved_path,
            photo_sha256=photo_sha256,
            status='queued'
        )

        AIGateway.increment_user_quota(request.user)

        try:
            process_fit_check_task.delay(str(fit_check.id))
        except Exception as task_err:
            logger.error(f"Celery task enqueue failed: {task_err}", exc_info=True)
            fit_check.status = 'failed'
            fit_check.error_code = 'task_queue_unavailable'
            fit_check.save(update_fields=['status', 'error_code'])
            return Response({
                'success': False,
                'error_code': 'queue_unavailable',
                'message': 'Background task queue is temporarily unavailable. Please retry shortly.',
                'errors': {'server': ['Task queue unavailable.']}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})

        return Response({
            'success': True,
            'status': 'queued',
            'scan_id': str(fit_check.id),
            'fit_check_id': str(fit_check.id),
            'poll_url': f"/api/closet/ai-scan/{fit_check.id}/",
            'poll_after_s': 3,
            'message': 'Garment image queued for asynchronous AI analysis.'
        }, status=status.HTTP_202_ACCEPTED)


class ClosetAIScanPollView(APIView):
    """
    GET /api/closet/ai-scan/<uuid:pk>/
    Poll status and retrieve result of an asynchronous AI garment scan (P-05).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request, pk):
        from closet.models import FitCheck
        from closet.serializers import FitCheckSerializer
        fit_check = FitCheck.objects.filter(id=pk, user=request.user).first()
        if not fit_check:
            return Response({
                'success': False,
                'error_code': 'not_found',
                'message': 'AI scan job not found.'
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = FitCheckSerializer(fit_check, context={'request': request})
        return Response({
            'success': True,
            'status': fit_check.status,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

