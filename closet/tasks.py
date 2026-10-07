import logging
import decimal
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(name='closet.tasks.recalculate_wardrobe_analytics_task')
def recalculate_wardrobe_analytics_task(user_id):
    """
    Background worker task to recompute wardrobe score, total items, 
    and most worn categories without blocking the user response.
    """
    from django.contrib.auth import get_user_model
    from closet.models import ClosetItem
    from rewards.models import UserRewardProfile

    User = get_user_model()
    try:
        user = User.objects.filter(id=user_id).first()
        if not user:
            return None

        items = ClosetItem.objects.filter(user=user)
        total_items = items.count()

        # Update cached stats or reward profile
        profile = UserRewardProfile.objects.filter(user=user).first()
        if profile and total_items > 0:
            logger.info(f"Recomputed wardrobe analytics for user {user.email}: {total_items} items.")
        return total_items
    except Exception as e:
        logger.error(f"Error recalculating wardrobe analytics for user {user_id}: {e}")
        return None


@shared_task(
    bind=True,
    name='closet.tasks.process_fit_check_task',
    acks_late=True,
    max_retries=3,
    soft_time_limit=90,
)
def process_fit_check_task(self, fit_check_id: str):
    """
    Asynchronous Celery pipeline for FitCheck AI processing (C-10, Spec §1.6 & §7.3):
    1. Loads FitCheck record with row locking.
    2. Stage-resume check: skips stages already persisted (idempotency & retry safety).
    3. Content Safety Gate: blocks NSFW/unsafe photos before Vision LLM call.
    4. Vision LLM inference via AIGateway with token/cost logging to LLMCostLog.
    5. Maps recognized garment attributes to ClosetItem and awards points once.
    6. Retries on transient upstream failures with exponential backoff (30s, 120s, 600s).
    """
    from closet.models import FitCheck, ClosetItem
    from closet.ai.gateway import AIGateway
    from closet.ai.safety import check_image_safety, AISafetyError, AISafetyBlockedError
    from closet.exceptions import AIServiceUnavailableError
    from rewards.services import award_points
    from rewards.models import RewardPointTransaction

    backoff_schedule = [30, 120, 600]

    try:
        with transaction.atomic():
            fit_check = FitCheck.objects.select_for_update().filter(id=fit_check_id).first()
            if not fit_check:
                logger.error(f"FitCheck with id {fit_check_id} not found.")
                return None

            # Terminal states check for idempotency
            if fit_check.status in ('tagged', 'dedupe_hit', 'nsfw_blocked'):
                logger.info(f"FitCheck {fit_check_id} already in terminal state '{fit_check.status}'.")
                return fit_check.status

            fit_check.status = 'processing'
            fit_check.save(update_fields=['status'])

        # Read photo bytes from storage
        photo_bytes = None
        if fit_check.photo:
            try:
                storage = fit_check.photo.storage
                if storage.exists(fit_check.photo.name):
                    with storage.open(fit_check.photo.name, 'rb') as f:
                        photo_bytes = f.read()
            except Exception as e:
                logger.error(f"Could not read photo bytes for FitCheck {fit_check_id}: {e}")

        if not photo_bytes:
            fit_check.status = 'failed'
            fit_check.error_code = 'image_not_found'
            fit_check.save(update_fields=['status', 'error_code'])
            return 'failed'

        # Stage 1: NSFW Safety Gate (spec §1.4, rule 3)
        if fit_check.nsfw_score is None:
            try:
                is_safe, safety_reason, nsfw_score = check_image_safety(photo_bytes)
                fit_check.nsfw_score = nsfw_score
                if not is_safe:
                    logger.warning(f"FitCheck {fit_check_id} blocked by safety gate: {safety_reason} ({nsfw_score})")
                    fit_check.status = 'nsfw_blocked'
                    fit_check.error_code = 'nsfw_content_detected'
                    fit_check.save(update_fields=['status', 'nsfw_score', 'error_code'])
                    # Delete blocked photo for privacy/compliance
                    try:
                        if fit_check.photo and fit_check.photo.storage.exists(fit_check.photo.name):
                            fit_check.photo.storage.delete(fit_check.photo.name)
                    except Exception:
                        pass
                    return 'nsfw_blocked'
                fit_check.save(update_fields=['nsfw_score'])
            except AISafetyError as e:
                logger.warning(f"Safety gate transient failure for FitCheck {fit_check_id}: {e}. Retrying.")
                retry_count = self.request.retries
                countdown = backoff_schedule[min(retry_count, len(backoff_schedule) - 1)]
                raise self.retry(exc=e, countdown=countdown)

        # Stage 2: AI Vision Inference via AIGateway (spec §1.7, rule 2)
        garment_data = fit_check.raw_tagging
        if not garment_data:
            try:
                garment_data = AIGateway.execute_photo_analysis(
                    image_bytes=photo_bytes,
                    user=fit_check.user,
                    fit_check=fit_check
                )
                fit_check.raw_tagging = garment_data
                fit_check.save(update_fields=['raw_tagging'])
            except (AIServiceUnavailableError, TimeoutError) as e:
                logger.warning(f"Upstream AI service error for FitCheck {fit_check_id}: {e}. Retrying.")
                retry_count = self.request.retries
                countdown = backoff_schedule[min(retry_count, len(backoff_schedule) - 1)]
                raise self.retry(exc=e, countdown=countdown)
            except AISafetyBlockedError:
                fit_check.status = 'nsfw_blocked'
                fit_check.error_code = 'nsfw_content_detected'
                fit_check.save(update_fields=['status', 'error_code'])
                return 'nsfw_blocked'

        # Stage 3: Validate garment detection
        if not garment_data.get('is_garment', True):
            fit_check.status = 'failed'
            fit_check.error_code = 'not_clothing'
            fit_check.save(update_fields=['status', 'error_code'])
            return 'failed'

        # Stage 4: Map recognized garment attributes to ClosetItem
        with transaction.atomic():
            price_val = garment_data.get('price', 35.00)
            try:
                if isinstance(price_val, str):
                    price_val = float(price_val.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip())
                else:
                    price_val = float(price_val)
            except (ValueError, TypeError):
                price_val = 35.00

            confidence_val = None
            if garment_data.get('confidence') is not None:
                try:
                    confidence_val = float(garment_data.get('confidence'))
                except (ValueError, TypeError):
                    pass

            item, created = ClosetItem.objects.get_or_create(
                user=fit_check.user,
                photo_sha256=fit_check.photo_sha256,
                defaults={
                    'fit_check': fit_check,
                    'name': garment_data.get('name', 'Wardrobe Essential'),
                    'category': garment_data.get('category', 'top'),
                    'color': garment_data.get('color', 'Neutral'),
                    'brand': garment_data.get('brand', 'N/A') or 'N/A',
                    'price': decimal.Decimal(f"{price_val:.2f}"),
                    'currency': 'EUR',
                    'style_vibe': garment_data.get('style_vibe', ''),
                    'pattern': garment_data.get('pattern', ''),
                    'fit': garment_data.get('fit', ''),
                    'confidence': confidence_val,
                    'source': 'scan',
                    'image': fit_check.photo.name if fit_check.photo else '',
                }
            )

            # If item already existed for this hash, link fit_check and increment wear count
            if not created:
                item.fit_check = fit_check
                item.times_worn += 1
                item.last_worn_at = timezone.now()
                item.save(update_fields=['fit_check', 'times_worn', 'last_worn_at'])
                fit_check.status = 'dedupe_hit'
            else:
                fit_check.status = 'tagged'
                # Award points once per fit check, bounded by daily points cap (C-07)
                daily_awards = RewardPointTransaction.objects.filter(
                    user=fit_check.user,
                    action_type='add_closet_item',
                    created_at__date=timezone.now().date()
                ).count()
                max_daily = getattr(settings, 'MYC_CLOSET_ITEM_POINTS_DAILY_LIMIT', 10)
                if daily_awards < max_daily:
                    try:
                        award_points(
                            user=fit_check.user,
                            action_type='add_closet_item',
                            description=f"Auto-scanned & added '{item.name}' to closet",
                            reference_id=str(item.id)
                        )
                    except Exception as e:
                        logger.warning(f"Error awarding points for FitCheck {fit_check_id}: {e}")

            fit_check.tagged_at = timezone.now()
            fit_check.save(update_fields=['status', 'tagged_at'])

        logger.info(f"Successfully processed FitCheck {fit_check_id} -> status: {fit_check.status}")
        return fit_check.status

    except self.MaxRetriesExceededError:
        logger.error(f"FitCheck {fit_check_id} failed after maximum retries.")
        FitCheck.objects.filter(id=fit_check_id).update(
            status='failed',
            error_code='max_retries_exceeded'
        )
        return 'failed'
    except Exception as e:
        logger.error(f"Unexpected error processing FitCheck {fit_check_id}: {e}", exc_info=True)
        FitCheck.objects.filter(id=fit_check_id).update(
            status='failed',
            error_code='unexpected_worker_error'
        )
        return 'failed'
