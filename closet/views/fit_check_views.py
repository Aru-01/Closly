import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from closet.models import FitCheck, ClosetItem, LLMCostLog
from closet.serializers import FitCheckSerializer, ClosetItemSerializer, LLMCostLogSerializer
from closet.utils import validate_and_sanitize_image, persist_sanitized_image
from closet.ai.gateway import AIGateway
from closet.tasks import process_fit_check_task
from closet.exceptions import AIServiceUnavailableError, AIDailyLimitExceededError, AIImageValidationError
from users.throttling import AIScanUserRateThrottle
from users.utils.common_utils import has_user_consent, record_user_consent

logger = logging.getLogger(__name__)


class FitCheckCreateView(APIView):
    """
    POST /api/closet/fit-checks/
    Asynchronous FitCheck creation and queuing endpoint (Spec §1.1, §7.2):
    1. Enforces GDPR Article 7 explicit consent for photo AI processing (HTTP 403 consent_required).
    2. Enforces AI Killswitch (HTTP 503) & per-user daily quota (HTTP 429).
    3. In-memory validation, EXIF stripping, downscaling to <= 1024px, and SHA-256 computation.
    4. Exact-duplicate short-circuit (dedupe_hit) returns HTTP 200 without charging quota or LLM.
    5. Saves photo privately and enqueues Celery background task (process_fit_check_task).
    6. Returns HTTP 202 Accepted with status 'queued' and polling recommendation.
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
        # 1. Enforce explicit user consent server-side (GDPR Art. 7, Spec §5.5)
        if not has_user_consent(request.user, kind='photo_ai_processing'):
            return Response({
                'success': False,
                'error_code': 'consent_required',
                'message': 'Explicit consent for photo and AI styling processing is required before using the AI closet scanner.',
                'consent_type': 'photo_ai_processing',
                'required_version': '1.0'
            }, status=status.HTTP_403_FORBIDDEN)

        # 2. Check killswitch and daily quota
        try:
            AIGateway.check_preconditions(request.user)
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

        # 3. Read image file
        image_file = request.FILES.get('image') or request.FILES.get('photo') or request.FILES.get('file')
        if not image_file:
            return Response({
                'success': False,
                'error_code': 'missing_image',
                'message': 'No image file provided. Please capture or upload a cloth image.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 4. In-memory validation, EXIF stripping, downscaling & SHA-256
        try:
            sanitized_bytes, photo_sha256, mime = validate_and_sanitize_image(image_file)
        except AIImageValidationError as e:
            return Response({
                'success': False,
                'error_code': 'invalid_image',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Image preprocessing error: {e}", exc_info=True)
            return Response({
                'success': False,
                'error_code': 'image_processing_failed',
                'message': 'Failed to process and sanitize garment image.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 5. Exact-duplicate short-circuit (Spec §1.5)
        existing_fc = FitCheck.objects.filter(
            user=request.user,
            photo_sha256=photo_sha256,
            status__in=['tagged', 'dedupe_hit']
        ).first()

        if existing_fc:
            logger.info(f"FitCheck dedupe hit for user {request.user.id} and hash {photo_sha256[:10]}")
            items_qs = ClosetItem.objects.filter(user=request.user, photo_sha256=photo_sha256)
            serializer = ClosetItemSerializer(items_qs, many=True, context={'request': request})
            return Response({
                'success': True,
                'id': str(existing_fc.id),
                'status': 'dedupe_hit',
                'message': 'Exact image already analyzed and indexed in your closet.',
                'items': serializer.data
            }, status=status.HTTP_200_OK)

        # 6. Save sanitized image privately under user folder
        saved_path = persist_sanitized_image(
            sanitized_bytes,
            folder=f"fit_checks/{request.user.id}",
            prefix="fc_"
        )

        # 7. Create FitCheck row in 'queued' state
        fit_check = FitCheck.objects.create(
            user=request.user,
            photo=saved_path,
            photo_sha256=photo_sha256,
            status='queued'
        )

        # 8. Increment user daily quota counter
        AIGateway.increment_user_quota(request.user)

        # 9. Enqueue Celery background task
        try:
            process_fit_check_task.delay(str(fit_check.id))
        except Exception as task_err:
            logger.error(f"Could not enqueue Celery task for FitCheck {fit_check.id}: {task_err}", exc_info=True)
            # If Celery broker is unavailable, run synchronously in fallback or mark failed
            fit_check.status = 'failed'
            fit_check.error_code = 'task_queue_unavailable'
            fit_check.save(update_fields=['status', 'error_code'])
            return Response({
                'success': False,
                'error_code': 'queue_unavailable',
                'message': 'Background task queue is temporarily unavailable. Please retry shortly.'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})

        # 10. HTTP 202 Accepted
        return Response({
            'success': True,
            'id': str(fit_check.id),
            'status': 'queued',
            'poll_after_s': 3,
            'message': 'FitCheck queued for AI processing.'
        }, status=status.HTTP_202_ACCEPTED)


class FitCheckDetailView(APIView):
    """
    GET /api/closet/fit-checks/<uuid:pk>/
    FitCheck status inspection and polling endpoint:
    - Enforces strict user ownership (User A cannot inspect User B's FitCheck).
    - Returns current status ('queued', 'processing', 'tagged', 'dedupe_hit', 'failed', 'nsfw_blocked').
    - Returns recognized closet items when status is 'tagged' or 'dedupe_hit'.
    - Returns clean, safe error messages on failure without leaking internal provider diagnostics.
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
        fit_check = FitCheck.objects.filter(id=pk).first()
        if not fit_check:
            return Response({
                'success': False,
                'error_code': 'not_found',
                'message': 'FitCheck record not found.'
            }, status=status.HTTP_404_NOT_FOUND)

        # Enforce strict IDOR ownership check
        if fit_check.user != request.user:
            logger.warning(f"IDOR attempt: User {request.user.id} tried to access FitCheck {pk} owned by User {fit_check.user_id}")
            return Response({
                'success': False,
                'error_code': 'forbidden',
                'message': 'You do not have permission to view this FitCheck record.'
            }, status=status.HTTP_403_FORBIDDEN)

        items_qs = ClosetItem.objects.filter(user=request.user, fit_check=fit_check)
        items_data = ClosetItemSerializer(items_qs, many=True, context={'request': request}).data

        response_data = {
            'id': str(fit_check.id),
            'status': fit_check.status,
            'nsfw_score': fit_check.nsfw_score,
            'tagging_model': fit_check.tagging_model,
            'error_code': fit_check.error_code,
            'items': items_data,
            'created_at': fit_check.created_at,
            'tagged_at': fit_check.tagged_at
        }

        # Safe human-friendly status messages
        if fit_check.status == 'nsfw_blocked':
            response_data['message'] = "Uploaded image violates content safety guidelines and was rejected."
        elif fit_check.status == 'failed':
            if fit_check.error_code == 'not_clothing':
                response_data['message'] = "The uploaded image does not appear to be a clothing item."
            else:
                response_data['message'] = "AI processing could not identify the garment. Please retry with a clearer photo."
        elif fit_check.status in ('tagged', 'dedupe_hit'):
            response_data['message'] = "Garment analysis completed successfully."
        else:
            response_data['message'] = "FitCheck is being processed by AI."

        return Response({
            'success': True,
            'data': response_data
        }, status=status.HTTP_200_OK)


class ConsentRecordView(APIView):
    """
    GET / POST /api/closet/consent/
    GDPR Article 7 Consent management endpoint for Photo & AI Styling Processing:
    GET: Checks if current user has active consent.
    POST: Grants or revokes consent with auditable timestamp, IP, and user-agent hash.
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
    GET /api/closet/costs/
    Provides visibility into AI token consumption, latency, and estimated EUR costs for the user.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        logs = LLMCostLog.objects.filter(user=request.user).order_by('-created_at')[:50]
        serializer = LLMCostLogSerializer(logs, many=True)
        total_cents = sum(l.cost_cents for l in logs)
        return Response({
            'success': True,
            'data': {
                'total_cost_cents': float(total_cents),
                'count': len(logs),
                'logs': serializer.data
            }
        }, status=status.HTTP_200_OK)
