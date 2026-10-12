import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from closet.serializers import ClosetItemSerializer, FitCheckSerializer
from closet.services import (
    handle_fit_check_submission,
    ConsentRequiredError,
    TaskQueueUnavailableError,
)
from closet.exceptions import (
    AIServiceUnavailableError,
    AIDailyLimitExceededError,
    AIImageValidationError,
)
from users.validators import validate_image_file
from users.throttling import AIScanUserRateThrottle

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["AI Wardrobe Scanner & Vision"],
    summary="AI Garment Scanner (Async Upload)",
    description=(
        "Uploads a garment image (camera snap or gallery photo) for AI attribute extraction.\n\n"
        "**Flow:**\n"
        "1. Validates explicit consent (`photo_ai_processing`).\n"
        "2. Executes Pre-Scanner NSFW Safety Gate (fails closed if inappropriate).\n"
        "3. Returns HTTP `202 Accepted` immediately with `poll_url` (<50ms).\n"
        "4. Celery worker analyzes garment in background and extracts category, color, vibe, and tags.\n"
        "5. Mobile client polls `GET /api/closet/ai-scan/{id}/` or waits for Push Notification."
    ),
    responses={
        202: OpenApiResponse(description="Garment photo queued for asynchronous AI analysis"),
        400: OpenApiResponse(description="Invalid or missing image file"),
        403: OpenApiResponse(description="Missing photo_ai_processing consent"),
        422: OpenApiResponse(description="Image blocked by automated NSFW/Safety gate"),
        503: OpenApiResponse(description="AI scanning service high traffic retry header"),
    }
)
class ClosetAIScanView(APIView):
    """
    Skinny View: Handles multipart upload validation and delegates scanning to ai_vision_services.
    POST /api/closet/ai-scan/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AIScanUserRateThrottle]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
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

        try:
            result = handle_fit_check_submission(request.user, image_file, folder_prefix="scan_")
        except ConsentRequiredError:
            return Response({
                'success': False,
                'error_code': 'consent_required',
                'message': 'Explicit consent for photo and AI styling processing is required before using the AI closet scanner.',
                'consent_type': 'photo_ai_processing',
                'required_version': '1.0',
                'errors': {'consent': ['Photo and AI styling processing consent required.']}
            }, status=status.HTTP_403_FORBIDDEN)
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
        except AIImageValidationError as e:
            return Response({
                'success': False,
                'error_code': 'invalid_image',
                'message': str(e),
                'errors': {'image': [str(e)]}
            }, status=status.HTTP_400_BAD_REQUEST)
        except TaskQueueUnavailableError:
            return Response({
                'success': False,
                'error_code': 'queue_unavailable',
                'message': 'Background task queue is temporarily unavailable. Please retry shortly.',
                'errors': {'server': ['Task queue unavailable.']}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})

        if result.get('is_duplicate'):
            item = result.get('item')
            if item:
                serializer = ClosetItemSerializer(item, context={'request': request})
                return Response({
                    'success': True,
                    'status': 'dedupe_hit',
                    'message': result.get('message'),
                    'data': {
                        'item': serializer.data,
                        'is_duplicate': True,
                    }
                }, status=status.HTTP_200_OK)

        fit_check = result['fit_check']
        return Response({
            'success': True,
            'status': 'queued',
            'scan_id': str(fit_check.id),
            'fit_check_id': str(fit_check.id),
            'poll_url': f"/api/closet/ai-scan/{fit_check.id}/",
            'poll_after_s': 3,
            'message': 'Garment image queued for asynchronous AI analysis.'
        }, status=status.HTTP_202_ACCEPTED)


@extend_schema(
    tags=["AI Wardrobe Scanner & Vision"],
    summary="Poll AI Garment Scan Status",
    description="Retrieves the current status and extracted attributes of an asynchronous AI garment scan job.",
    responses={
        200: OpenApiResponse(description="AI scan status and garment data"),
        404: OpenApiResponse(description="Job ID not found or unauthorized"),
    }
)
class ClosetAIScanPollView(APIView):
    """
    Skinny View: Poll status and retrieve result of an asynchronous AI garment scan (P-05).
    GET /api/closet/ai-scan/<uuid:pk>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request, pk):
        from closet.models import FitCheck
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
