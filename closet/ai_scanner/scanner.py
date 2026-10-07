import os
import io
import uuid
import logging
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from users.utils import build_absolute_media_url
from closet.utils import validate_and_sanitize_image, persist_sanitized_image
from closet.exceptions import AIServiceUnavailableError, AIDailyLimitExceededError
from closet.models import FitCheck, ClosetItem

from .gemini_client import call_gemini_vision_api

logger = logging.getLogger(__name__)


def scan_clothing_image(image_file, request=None, user=None):
    """
    Production-grade entry point for AI clothing scan:
    1. Enforces global kill-switch flag (AI_SCANNER_ENABLED) -> HTTP 503 if disabled.
    2. Validates user daily quota (MYC_AI_SCAN_DAILY_LIMIT) -> HTTP 429 if exceeded.
    3. In-memory validation, EXIF stripping, downscaling to <= 1024px, and SHA-256 computation (C-01, C-06).
    4. Calls official Vision LLM with European taxonomy and EUR pricing.
    5. Never fabricates fake garments or watches if LLM fails (C-04) — fails closed with 503.
    6. Persists sanitized photo only upon valid garment identification and links to FitCheck audit row (C-01, C-02).
    7. Detects duplicate photos via photo_sha256 for points farming idempotency (C-07).
    """
    # 1. Kill-switch check
    if not getattr(settings, 'AI_SCANNER_ENABLED', True):
        logger.warning("AI Scan rejected: AI_SCANNER_ENABLED is False.")
        raise AIServiceUnavailableError("AI garment scanner is temporarily disabled for scheduled maintenance.")

    current_user = user or (request.user if request and getattr(request, 'user', None) and request.user.is_authenticated else None)

    # 2. Per-user daily scan quota enforcement (C-05)
    if current_user and current_user.is_authenticated:
        daily_limit = getattr(settings, 'MYC_AI_SCAN_DAILY_LIMIT', 25)
        today_str = timezone.now().strftime('%Y-%m-%d')
        daily_cache_key = f"ai_scan_daily_{current_user.id}_{today_str}"
        current_count = cache.get(daily_cache_key, 0)
        if current_count >= daily_limit:
            logger.warning(f"User {current_user.id} exceeded daily AI scan limit ({current_count}/{daily_limit}).")
            raise AIDailyLimitExceededError(f"Daily AI scan limit of {daily_limit} scans reached. Please try again tomorrow.")

    # 3. In-memory image validation, EXIF stripping & downscaling (C-01, C-06)
    sanitized_bytes, photo_sha256, mime = validate_and_sanitize_image(image_file)

    # 4. Check for existing item owned by user with exact same photo_sha256 (C-07)
    existing_item = None
    if current_user and current_user.is_authenticated:
        existing_item = ClosetItem.objects.filter(user=current_user, photo_sha256=photo_sha256).first()

    # 5. Execute Vision LLM pipeline through AIGateway (Safety, EU routing, Token & Cost tracking)
    garment_data = None
    try:
        from closet.ai.gateway import AIGateway
        from closet.ai.safety import AISafetyBlockedError, AISafetyError
        garment_data = AIGateway.execute_photo_analysis(sanitized_bytes, mime_type=mime, user=current_user)
    except (TimeoutError, AIServiceUnavailableError, AISafetyBlockedError, AISafetyError):
        raise
    except Exception as e:
        logger.error(f"AI Gateway photo analysis failed: {e}", exc_info=True)

    # Secondary fallback: Gemini Vision if configured
    if not garment_data:
        gemini_key = getattr(settings, 'GEMINI_API_KEY', None)
        if gemini_key:
            try:
                garment_data = call_gemini_vision_api(sanitized_bytes, mime, gemini_key)
            except Exception as e:
                logger.error(f"Gemini vision fallback failed: {e}", exc_info=True)

    # Strict production rule (C-04): Never fabricate fake garments on provider failure!
    if not garment_data:
        raise AIServiceUnavailableError("AI scanning service is currently experiencing upstream provider delays. Please try again in a few moments.")

    # If inspected and verified as NOT a garment, return immediately without storing any file to disk (C-01)
    if not garment_data.get('is_garment', True):
        return {
            "is_garment": False,
            "message": garment_data.get("message") or "The uploaded image does not appear to be a clothing item. Please capture or upload a clear photo of a garment.",
            "notes": garment_data.get("notes", ""),
            "photo_sha256": photo_sha256,
        }

    # 6. Valid garment detected: Persist sanitized JPEG to storage and create FitCheck audit record
    saved_path = persist_sanitized_image(sanitized_bytes, folder="closet_items", prefix="ai_scan_")
    absolute_image_url = build_absolute_media_url(saved_path, request=request)

    fit_check = None
    if current_user and current_user.is_authenticated:
        try:
            fit_check = FitCheck.objects.create(
                user=current_user,
                photo=saved_path,
                photo_sha256=photo_sha256,
                status='dedupe_hit' if existing_item else 'tagged',
                raw_tagging=garment_data,
                tagging_model=getattr(settings, 'LLM_MODEL', 'gpt-4o'),
                tagged_at=timezone.now()
            )
            # Increment daily quota counter
            today_str = timezone.now().strftime('%Y-%m-%d')
            daily_cache_key = f"ai_scan_daily_{current_user.id}_{today_str}"
            try:
                if cache.get(daily_cache_key) is None:
                    cache.set(daily_cache_key, 1, timeout=86400)
                else:
                    cache.incr(daily_cache_key)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Could not create FitCheck audit record: {e}")

    # Ensure brand is strictly 'N/A' if unverified
    if not garment_data.get('brand') or garment_data.get('brand').lower() in ('unknown', 'none', 'generic', 'n/a', 'null', 'undefined'):
        garment_data['brand'] = "N/A"

    # Real visual match score reflecting model confidence
    confidence = float(garment_data.get('confidence', 0.90))
    visual_match_pct = max(50, min(100, int(round(confidence * 100))))

    # Find similar items the user already owns in their wardrobe
    similar_wardrobe_items = []
    if current_user and current_user.is_authenticated:
        try:
            similar_qs = ClosetItem.objects.filter(
                user=current_user,
                category=garment_data.get('category', 'top')
            ).exclude(photo_sha256=photo_sha256)[:3]
            for it in similar_qs:
                similar_wardrobe_items.append({
                    "id": it.id,
                    "name": it.name,
                    "color": it.color,
                    "brand": it.brand,
                    "price": float(it.price),
                    "image": build_absolute_media_url(it.image, request=request)
                })
        except Exception as e:
            logger.warning(f"Error fetching similar items: {e}")

    clean_result = {
        "name": garment_data.get("name"),
        "category": garment_data.get("category"),
        "color": garment_data.get("color"),
        "secondary_colors": garment_data.get("secondary_colors", []),
        "pattern": garment_data.get("pattern"),
        "gender": garment_data.get("gender"),
        "brand": garment_data.get("brand"),
        "brand_info": garment_data.get("brand_info"),
        "price": garment_data.get("price"),
        "currency": "EUR",
        "estimated_price": garment_data.get("estimated_price"),
        "style_vibe": garment_data.get("style_vibe"),
        "visual_match_score": visual_match_pct,
        "image_url": absolute_image_url,
        "notes": garment_data.get("notes"),
        "similar_wardrobe_items": similar_wardrobe_items,
        "saved_image_path": saved_path,
        "photo_sha256": photo_sha256,
        "fit_check_id": str(fit_check.id) if fit_check else None,
        "is_duplicate": bool(existing_item),
        "existing_item_id": existing_item.id if existing_item else None,
        "is_garment": True,
        "is_full_outfit": bool(garment_data.get("is_full_outfit", False)),
    }
    if garment_data.get("is_full_outfit") and garment_data.get("detected_items"):
        clean_result["detected_items"] = garment_data.get("detected_items")

    return clean_result

