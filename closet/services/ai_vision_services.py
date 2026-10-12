import logging
from typing import Tuple, Dict, Any, Optional

from closet.models import FitCheck, ClosetItem
from closet.ai.gateway import AIGateway
from closet.tasks import process_fit_check_task
from closet.utils import validate_and_sanitize_image, persist_sanitized_image
from users.utils.common_utils import has_user_consent

logger = logging.getLogger(__name__)


class ConsentRequiredError(Exception):
    """Raised when user has not consented to AI photo processing."""
    pass


class TaskQueueUnavailableError(Exception):
    """Raised when background celery broker fails to accept task."""
    pass


def handle_fit_check_submission(
    user,
    image_file,
    folder_prefix: str = "fc_",
) -> Dict[str, Any]:
    """
    Core AI Vision Service: Processes an uploaded garment/outfit image.

    Flow:
    1. Enforces GDPR Art. 7 explicit consent for photo AI styling.
    2. Enforces AI Killswitch and daily user scan quotas.
    3. Validates, strips EXIF metadata, downscales, and computes SHA-256.
    4. Exact-duplicate short-circuit (dedupe_hit) avoids redundant LLM/Vision costs.
    5. Persists sanitized photo privately.
    6. Creates FitCheck in 'queued' state and increments quota.
    7. Enqueues background Celery task for async vision processing.
    """
    # 1. Enforce explicit user consent server-side (GDPR Art. 7, Spec §5.5)
    if not has_user_consent(user, kind='photo_ai_processing'):
        raise ConsentRequiredError("Explicit consent for photo and AI styling processing is required.")

    # 2. Check killswitch and daily quota
    AIGateway.check_preconditions(user)

    # 3. In-memory validation, EXIF stripping, downscaling & SHA-256
    sanitized_bytes, photo_sha256, mime = validate_and_sanitize_image(image_file)

    # 4. Check for duplicate FitCheck or ClosetItem
    existing_fc = (
        FitCheck.objects.filter(
            user=user,
            photo_sha256=photo_sha256,
            status__in=['tagged', 'dedupe_hit']
        )
        .prefetch_related('closet_items')
        .first()
    )

    if existing_fc:
        logger.info(f"FitCheck dedupe hit for user {user.id} and hash {photo_sha256[:10]}")
        items_qs = ClosetItem.objects.filter(user=user, photo_sha256=photo_sha256)
        return {
            'is_duplicate': True,
            'fit_check': existing_fc,
            'items': items_qs,
            'status': 'dedupe_hit',
            'message': 'Exact image already analyzed and indexed in your closet.',
        }

    # Also check if existing ClosetItem has this hash
    existing_item = ClosetItem.objects.filter(user=user, photo_sha256=photo_sha256).first()
    if existing_item:
        return {
            'is_duplicate': True,
            'item': existing_item,
            'status': 'dedupe_hit',
            'message': f"Item recognized in your digital closet! '{existing_item.name}'.",
        }

    # 5. Save sanitized image privately under user folder
    saved_path = persist_sanitized_image(
        sanitized_bytes,
        folder=f"fit_checks/{user.id}",
        prefix=folder_prefix,
    )

    # 6. Create FitCheck row in 'queued' state
    fit_check = FitCheck.objects.create(
        user=user,
        photo=saved_path,
        photo_sha256=photo_sha256,
        status='queued',
    )

    # 7. Increment user daily quota counter
    AIGateway.increment_user_quota(user)

    # 8. Enqueue Celery background task
    try:
        process_fit_check_task.delay(str(fit_check.id))
    except Exception as task_err:
        logger.error(f"Could not enqueue Celery task for FitCheck {fit_check.id}: {task_err}", exc_info=True)
        fit_check.status = 'failed'
        fit_check.error_code = 'task_queue_unavailable'
        fit_check.save(update_fields=['status', 'error_code'])
        raise TaskQueueUnavailableError("Background task queue is temporarily unavailable.")

    return {
        'is_duplicate': False,
        'fit_check': fit_check,
        'status': 'queued',
        'poll_url': f"/api/closet/ai-scan/{fit_check.id}/",
        'message': 'Garment image queued for asynchronous AI analysis.',
    }


def get_fit_check_details(user, fit_check_id) -> Tuple[Optional[FitCheck], Optional[Dict[str, Any]], Optional[str]]:
    """
    Retrieves FitCheck details with ownership verification and N+1 query elimination.

    OPTIMIZATION:
    - Uses prefetch_related('closet_items') to fetch all linked items in a single query.

    Returns:
        (fit_check, response_data, error_code)
    """
    fit_check = (
        FitCheck.objects.filter(id=fit_check_id)
        .prefetch_related('closet_items')
        .first()
    )

    if not fit_check:
        return None, None, 'not_found'

    # IDOR ownership check
    if fit_check.user_id != user.id:
        logger.warning(f"IDOR attempt: User {user.id} tried to access FitCheck {fit_check_id} owned by User {fit_check.user_id}")
        return None, None, 'forbidden'

    from closet.serializers import ClosetItemSerializer
    items_qs = fit_check.closet_items.all()
    items_data = ClosetItemSerializer(items_qs, many=True).data

    response_data = {
        'id': str(fit_check.id),
        'status': fit_check.status,
        'nsfw_score': fit_check.nsfw_score,
        'tagging_model': fit_check.tagging_model,
        'error_code': fit_check.error_code,
        'items': items_data,
        'created_at': fit_check.created_at,
        'tagged_at': fit_check.tagged_at,
    }

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

    return fit_check, response_data, None
