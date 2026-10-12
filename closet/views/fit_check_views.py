import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from closet.models import LLMCostLog
from closet.serializers import ClosetItemSerializer, LLMCostLogSerializer
from closet.services import (
    handle_fit_check_submission,
    get_fit_check_details,
    ConsentRequiredError,
    TaskQueueUnavailableError,
)
from closet.exceptions import (
    AIServiceUnavailableError,
    AIDailyLimitExceededError,
    AIImageValidationError,
)
from users.throttling import AIScanUserRateThrottle
from users.utils.common_utils import has_user_consent, record_user_consent

logger = logging.getLogger(__name__)


class FitCheckCreateView(APIView):
    """
    Skinny View: Asynchronous FitCheck creation and queuing endpoint (Spec §1.1, §7.2).
    Delegates validation, image sanitization, deduplication, and Celery dispatch to ai_vision_services.
    POST /api/closet/fit-checks/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AIScanUserRateThrottle]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=["FitCheck & Async AI Vision"],
        summary="Create and queue an asynchronous FitCheck AI scan",
        responses={
            202: OpenApiResponse(description="FitCheck queued for background AI processing"),
            200: OpenApiResponse(description="Deduplication hit - image already processed"),
            400: OpenApiResponse(description="Invalid or corrupted image format"),
            403: OpenApiResponse(description="Photo AI processing consent required"),
            429: OpenApiResponse(description="Daily AI scan quota exceeded"),
            503: OpenApiResponse(description="AI scanner temporarily disabled"),
        }
    )
    def post(self, request):
        image_file = request.FILES.get('image') or request.FILES.get('photo') or request.FILES.get('file')
        if not image_file:
            return Response({
                'success': False,
                'error_code': 'missing_image',
                'message': 'No image file provided. Please capture or upload a cloth image.'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = handle_fit_check_submission(request.user, image_file, folder_prefix="fc_")
        except ConsentRequiredError:
            return Response({
                'success': False,
                'error_code': 'consent_required',
                'message': 'Explicit consent for photo and AI styling processing is required before using the AI closet scanner.',
                'consent_type': 'photo_ai_processing',
                'required_version': '1.0'
            }, status=status.HTTP_403_FORBIDDEN)
        except AIServiceUnavailableError as e:
            return Response({
                'success': False,
                'error_code': 'service_unavailable',
                'message': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
        except AIDailyLimitExceededError as e:
            return Response({
                'success': False,
                'error_code': 'quota_exceeded',
                'message': str(e)
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except AIImageValidationError as e:
            return Response({
                'success': False,
                'error_code': 'invalid_image',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except TaskQueueUnavailableError:
            return Response({
                'success': False,
                'error_code': 'queue_unavailable',
                'message': 'Background task queue is temporarily unavailable. Please retry shortly.'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})
        except Exception as e:
            logger.error(f"FitCheck submission failed: {e}", exc_info=True)
            return Response({
                'success': False,
                'error_code': 'image_processing_failed',
                'message': 'Failed to process and sanitize garment image.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if result.get('is_duplicate'):
            existing_fc = result.get('fit_check')
            items_qs = result.get('items')
            items_data = ClosetItemSerializer(items_qs, many=True, context={'request': request}).data if items_qs is not None else []
            return Response({
                'success': True,
                'id': str(existing_fc.id),
                'status': 'dedupe_hit',
                'message': result.get('message'),
                'items': items_data
            }, status=status.HTTP_200_OK)

        fit_check = result['fit_check']
        return Response({
            'success': True,
            'id': str(fit_check.id),
            'status': 'queued',
            'poll_after_s': 3,
            'message': 'FitCheck queued for AI processing.'
        }, status=status.HTTP_202_ACCEPTED)


class FitCheckDetailView(APIView):
    """
    Skinny View: FitCheck status inspection and polling endpoint.
    Delegates ownership check and item prefetching to ai_vision_services.
    GET /api/closet/fit-checks/<uuid:pk>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    @extend_schema(
        tags=["FitCheck & Async AI Vision"],
        summary="Poll or inspect a FitCheck status",
        responses={
            200: OpenApiResponse(description="FitCheck record retrieved"),
            403: OpenApiResponse(description="Forbidden - cross-user access denied"),
            404: OpenApiResponse(description="FitCheck not found"),
        }
    )
    def get(self, request, pk):
        fit_check, response_data, error_code = get_fit_check_details(request.user, pk)

        if error_code == 'not_found':
            return Response({
                'success': False,
                'error_code': 'not_found',
                'message': 'FitCheck record not found.'
            }, status=status.HTTP_404_NOT_FOUND)

        if error_code == 'forbidden':
            return Response({
                'success': False,
                'error_code': 'forbidden',
                'message': 'You do not have permission to view this FitCheck record.'
            }, status=status.HTTP_403_FORBIDDEN)

        return Response({
            'success': True,
            'data': response_data
        }, status=status.HTTP_200_OK)


class ConsentRecordView(APIView):
    """
    Skinny View: GDPR Article 7 Consent management endpoint for Photo & AI Styling Processing.
    GET / POST /api/closet/consent/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        kind = request.query_params.get('kind', 'photo_ai_processing')
        is_granted = has_user_consent(request.user, kind=kind)
        return Response({
            'success': True,
            'kind': kind,
            'granted': is_granted,
            'version': '1.0'
        }, status=status.HTTP_200_OK)

    def post(self, request):
        kind = request.data.get('kind', 'photo_ai_processing')
        granted = request.data.get('granted', True)
        if isinstance(granted, str):
            granted = granted.lower() in ('true', '1', 'yes')

        version = request.data.get('version', '1.0')
        consent_obj = record_user_consent(
            user=request.user,
            kind=kind,
            granted=granted,
            request=request,
            version=version
        )
        action_verb = "granted" if granted else "revoked"
        logger.info(f"User {request.user.id} {action_verb} consent for {kind} (version {version}).")
        return Response({
            'success': True,
            'message': f"Consent for '{kind}' successfully {action_verb}.",
            'data': {
                'kind': kind,
                'granted': consent_obj.granted,
                'version': consent_obj.version,
                'occurred_at': consent_obj.occurred_at
            }
        }, status=status.HTTP_200_OK)


class LLMCostLogListView(APIView):
    """
    Skinny View: Provides visibility into AI token consumption, latency, and estimated EUR costs.
    GET /api/closet/costs/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        logs = LLMCostLog.objects.filter(user=request.user).order_by('-created_at')[:50]
        serializer = LLMCostLogSerializer(logs, many=True)
        total_cents = sum(log_entry.cost_cents for log_entry in logs)
        return Response({
            'success': True,
            'data': {
                'total_cost_cents': float(total_cents),
                'count': len(logs),
                'logs': serializer.data
            }
        }, status=status.HTTP_200_OK)
