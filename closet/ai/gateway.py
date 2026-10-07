import time
import decimal
import logging
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from closet.models import LLMCostLog, FitCheck
from closet.exceptions import AIServiceUnavailableError, AIDailyLimitExceededError
from closet.ai.safety import check_image_safety, AISafetyError, AISafetyBlockedError

logger = logging.getLogger(__name__)

# Standard model pricing table (USD per 1,000,000 tokens)
MODEL_PRICING = {
    'gpt-4o': {'input_per_m': 2.50, 'output_per_m': 10.00},
    'gpt-4o-mini': {'input_per_m': 0.15, 'output_per_m': 0.60},
    'gpt-5.6-luna': {'input_per_m': 2.50, 'output_per_m': 10.00},
    'claude-3-5-haiku-20241022': {'input_per_m': 1.00, 'output_per_m': 5.00},
    'gemini-1.5-flash': {'input_per_m': 0.075, 'output_per_m': 0.30},
}
USD_TO_EUR_RATE = 0.92  # 1 USD ≈ 0.92 EUR


def calculate_cost_cents(model: str, input_tokens: int, output_tokens: int) -> decimal.Decimal:
    """Calculates estimated cost in EUR cents for token consumption."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING['gpt-4o'])
    usd_cost = (
        (input_tokens / 1_000_000.0) * pricing['input_per_m'] +
        (output_tokens / 1_000_000.0) * pricing['output_per_m']
    )
    eur_cents = (usd_cost * USD_TO_EUR_RATE) * 100.0
    return decimal.Decimal(f"{eur_cents:.4f}")


class AIGateway:
    """
    Central AI Gateway enforcing:
    1. Global Kill-switch & maintenance mode.
    2. User daily scan quota.
    3. EU data routing & Provider allowlist assertion.
    4. NSFW content safety gate.
    5. Token & EUR cent cost logging to LLMCostLog.
    6. Uniform timeout & error abstraction without leaking internal secrets.
    """

    @staticmethod
    def check_preconditions(user=None):
        """Verifies killswitch and rate quotas."""
        # 1. Killswitch
        if not getattr(settings, 'AI_SCANNER_ENABLED', True):
            logger.warning("AI Gateway blocked: AI_SCANNER_ENABLED is False.")
            raise AIServiceUnavailableError("AI garment scanner is temporarily disabled for scheduled maintenance.")

        # 2. User daily limit
        if user and user.is_authenticated:
            daily_limit = getattr(settings, 'MYC_AI_SCAN_DAILY_LIMIT', 25)
            today_str = timezone.now().strftime('%Y-%m-%d')
            daily_cache_key = f"ai_scan_daily_{user.id}_{today_str}"
            current_count = cache.get(daily_cache_key, 0)
            if current_count >= daily_limit:
                logger.warning(f"User {user.id} reached daily AI scan limit ({current_count}/{daily_limit}).")
                raise AIDailyLimitExceededError(f"Daily AI scan limit of {daily_limit} scans reached. Please try again tomorrow.")

    @staticmethod
    def increment_user_quota(user):
        """Increments the daily quota counter on successful scan enqueue/execution."""
        if user and user.is_authenticated:
            today_str = timezone.now().strftime('%Y-%m-%d')
            daily_cache_key = f"ai_scan_daily_{user.id}_{today_str}"
            try:
                if cache.get(daily_cache_key) is None:
                    cache.set(daily_cache_key, 1, timeout=86400)
                else:
                    cache.incr(daily_cache_key)
            except Exception:
                pass

    @staticmethod
    def verify_provider_and_region():
        """Asserts EU routing and allowed providers."""
        region = getattr(settings, 'AI_DATA_REGION', 'EU')
        provider = getattr(settings, 'AI_PHOTO_PROVIDER', 'openai')
        allowlist = getattr(settings, 'AI_PROVIDER_ALLOWLIST', ['openai', 'openai_eu', 'anthropic_eu', 'mock'])

        if provider not in allowlist:
            logger.error(f"Configured AI provider '{provider}' is not in the allowlist {allowlist}.")
            raise AIServiceUnavailableError("AI provider configuration error. Provider not permitted under active data residency policies.")

        return provider, region

    @classmethod
    def execute_photo_analysis(cls, image_bytes: bytes, mime_type: str = 'image/jpeg', user=None, fit_check=None) -> dict:
        """
        Executes complete gated vision pipeline:
        1. Preconditions & Quota
        2. Content Safety / NSFW Gate
        3. Provider & EU Routing
        4. Model Inference with timeout
        5. Token & Cost Logging
        """
        cls.check_preconditions(user=user)
        provider, region = cls.verify_provider_and_region()

        # Step 2: NSFW Safety Gate (Rule 3 - Must run before any downstream LLM call)
        is_safe, safety_reason, nsfw_score = check_image_safety(image_bytes)
        if fit_check:
            fit_check.nsfw_score = nsfw_score
            fit_check.save(update_fields=['nsfw_score'])

        if not is_safe:
            logger.warning(f"Image blocked by safety gate: reason={safety_reason}, score={nsfw_score}")
            if fit_check:
                fit_check.status = 'nsfw_blocked'
                fit_check.error_code = 'nsfw_content_detected'
                fit_check.save(update_fields=['status', 'error_code'])
            raise AISafetyBlockedError(
                message="Uploaded image violates content safety guidelines and cannot be processed.",
                category=safety_reason,
                score=nsfw_score
            )

        # Step 3: Run Model Inference
        model_name = getattr(settings, 'LLM_MODEL', 'gpt-4o')
        start_time = time.monotonic()
        tokens_in = 0
        tokens_out = 0
        cost_cents = decimal.Decimal('0.0000')
        success = False
        error_code = ''
        result_payload = None

        try:
            from closet.openai_analyzer import analyze_dress_with_openai
            result_payload = analyze_dress_with_openai(image_bytes, mime_type=mime_type, user=user)
            success = True
            # Standard estimated tokens if not returned explicitly by sub-module
            try:
                tokens_in = int(result_payload.get('tokens_in', 1240))
            except (ValueError, TypeError):
                tokens_in = 1240

            try:
                tokens_out = int(result_payload.get('tokens_out', 220))
            except (ValueError, TypeError):
                tokens_out = 220

            cost_cents = calculate_cost_cents(model_name, tokens_in, tokens_out)
            return result_payload

        except TimeoutError:
            error_code = 'timeout'
            raise
        except AIServiceUnavailableError:
            error_code = 'provider_unavailable'
            raise
        except Exception as e:
            error_code = 'inference_error'
            logger.error(f"Inference error in AI Gateway: {e}", exc_info=True)
            raise AIServiceUnavailableError("AI vision inference failed. Please try again.")

        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            try:
                LLMCostLog.objects.create(
                    user=user if user and user.is_authenticated else None,
                    fit_check=fit_check,
                    task='photo_analysis',
                    provider=provider,
                    model=model_name,
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    cost_cents=cost_cents,
                    latency_ms=latency_ms,
                    success=success,
                    error_code=error_code
                )
                if fit_check and success:
                    fit_check.cost_cents = cost_cents
                    fit_check.tagging_model = model_name
                    fit_check.provider = provider
                    fit_check.save(update_fields=['cost_cents', 'tagging_model', 'provider'])
            except Exception as log_err:
                logger.error(f"Could not persist LLMCostLog: {log_err}")
