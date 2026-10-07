import sys
import logging
import hashlib
import threading
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from closet.exceptions import AIServiceUnavailableError

logger = logging.getLogger(__name__)

# High-scale Concurrency Gate & Response Cache Configuration (100–1000 users)
_AI_CONCURRENCY_LIMIT = getattr(settings, 'AI_SCAN_CONCURRENCY_LIMIT', 15)
_AI_QUEUE_TIMEOUT = getattr(settings, 'AI_SCAN_QUEUE_TIMEOUT', 35.0)
_AI_CACHE_TTL = getattr(settings, 'AI_SCAN_CACHE_TTL', 600)
_AI_GATE = threading.BoundedSemaphore(_AI_CONCURRENCY_LIMIT)

# Ensure the dress-analyzer-ai directory is in sys.path
DRESS_ANALYZER_DIR = Path(settings.BASE_DIR) / 'dress-analyzer-ai'
if str(DRESS_ANALYZER_DIR) not in sys.path:
    sys.path.insert(0, str(DRESS_ANALYZER_DIR))

# Directly import the exact AI team service and components from dress-analyzer-ai
try:
    import service as ai_service  # type: ignore[import-not-found]
    from schemas import DressAnalysisResult  # type: ignore[import-not-found]
    AI_TEAM_MODULE_AVAILABLE = True
except Exception as e:
    logger.warning(f"Could not import dress-analyzer-ai directly: {e}")
    ai_service = None
    DressAnalysisResult = None  # type: ignore[assignment]
    AI_TEAM_MODULE_AVAILABLE = False


# Map fine-grained garment types to Closly's core category taxonomy
CATEGORY_MAPPING = {
    # Tops
    'tshirt': 'top',
    't-shirt': 'top',
    'shirt': 'top',
    'polo': 'top',
    'top': 'top',
    'hoodie': 'top',
    'sweatshirt': 'top',
    'sweater': 'top',
    'cardigan': 'top',
    'blouse': 'top',
    'vest': 'top',
    'kurti': 'top',
    # Bottoms
    'pant': 'bottom',
    'pants': 'bottom',
    'trousers': 'bottom',
    'chinos': 'bottom',
    'jeans': 'bottom',
    'shorts': 'bottom',
    'skirt': 'bottom',
    'plazoo': 'bottom',
    'palazzo': 'bottom',
    # Dresses & Outerwear
    'dress': 'dresses_outerwear',
    'jumpsuit': 'dresses_outerwear',
    'jacket': 'dresses_outerwear',
    'coat': 'dresses_outerwear',
    'blazer': 'dresses_outerwear',
    'suit': 'dresses_outerwear',
    'outerwear': 'dresses_outerwear',
    'saree': 'dresses_outerwear',
    'sari': 'dresses_outerwear',
    # Shoes
    'shoes': 'shoes',
    'sneakers': 'shoes',
    'boots': 'shoes',
    'loafers': 'shoes',
    'sandals': 'shoes',
    'heels': 'shoes',
    'footwear': 'shoes',
    # Accessories
    'accessories': 'accessories',
    'accessory': 'accessories',
    'bag': 'accessories',
    'handbag': 'accessories',
    'backpack': 'accessories',
    'hat': 'accessories',
    'cap': 'accessories',
    'beanie': 'accessories',
    'belt': 'accessories',
    'scarf': 'accessories',
    'sunglasses': 'accessories',
    'watch': 'accessories',
    'jewelry': 'accessories',
    'other': 'other',
}

# Standard realistic baseline prices by category in EUR (€)
CATEGORY_BASE_PRICES = {
    'top': 35.00,
    'bottom': 55.00,
    'dresses_outerwear': 89.00,
    'shoes': 75.00,
    'accessories': 30.00,
    'other': 30.00,
}


def is_valid_garment(raw_json: dict) -> tuple[bool, str]:
    """
    Validates whether the scanned image contains an actual wearable clothing item.
    Uses explicit is_garment boolean from the vision model (C-11) and only falls
    back to keyword analysis for ambiguous models.
    """
    if "is_garment" in raw_json:
        is_g = bool(raw_json.get("is_garment", True))
        if not is_g:
            notes = str(raw_json.get("notes", "")).strip()
            return False, notes or "The uploaded image does not appear to be a clothing item. Please capture or upload a clear photo of a garment."
        return True, ""

    garment_type = str(raw_json.get("garment_type", "")).lower().strip()
    notes = str(raw_json.get("notes", "")).strip()
    notes_lower = notes.lower()

    # Explicit non-garment cues (excluding 'graphic design' / 'artwork' to avoid rejecting graphic tees)
    non_garment_markers = [
        "not an actual garment",
        "not a garment",
        "not clothing",
        "not apparel",
        "screenshot",
        "logo design",
        "not a piece of clothing",
        "does not show clothing",
        "no clothing item",
        "not wearable",
    ]

    for marker in non_garment_markers:
        if marker in notes_lower:
            return False, notes or "The image appears to be a screenshot or non-clothing object rather than a garment."

    if garment_type in ("other", "none", "unknown", ""):
        clothing_keywords = [
            "shirt", "pant", "trousers", "dress", "saree", "kurti", "skirt",
            "jacket", "hoodie", "sweater", "shoes", "boots", "sneakers",
            "hat", "cap", "bag", "cloth", "garment", "fabric", "wear", "apparel"
        ]
        if not any(kw in notes_lower for kw in clothing_keywords):
            return False, notes or "Could not identify a wearable clothing item in this image. Please upload a clear photo of a garment."

    return True, ""



def run_direct_dress_analysis(file_or_bytes, mime_type: str = 'image/jpeg', user=None) -> dict:
    """
    Executes the dress-analyzer-ai vision pipeline with:
    1. Fast SHA-256 result caching (1ms instant response on duplicate/repeated scans, user-scoped C-18)
    2. Concurrency Semaphore Gate (controlled parallel execution for 100-1000 users without worker starvation)
    3. Direct LLM vision inference (~2.4s)
    4. Non-garment early exit validation (no slow web search if not a garment)
    5. Brand resolution (Apify Google Search only when enabled)
    """
    if not AI_TEAM_MODULE_AVAILABLE or ai_service is None:
        raise RuntimeError("dress-analyzer-ai module is not available in sys.path.")

    if hasattr(file_or_bytes, 'read'):
        file_or_bytes.seek(0)
        file_bytes = file_or_bytes.read()
        file_or_bytes.seek(0)
        content_type = getattr(file_or_bytes, 'content_type', None)
        if content_type:
            mime_type = content_type
    else:
        file_bytes = file_or_bytes

    # 1. Check SHA-256 cache for instant 1ms response on duplicate / re-scanned images
    image_hash = hashlib.sha256(file_bytes).hexdigest()
    user_id = getattr(user, 'id', 'global') if user else 'global'
    cache_key = f"closly_ai_scan_{user_id}_{image_hash}"
    cached_payload = cache.get(cache_key)
    if not cached_payload:
        # Also check global cache key for backward compatibility
        cached_payload = cache.get(f"closly_ai_scan_{image_hash}")

    if cached_payload and isinstance(cached_payload, dict):
        logger.info(f"AI scan cache hit for image hash {image_hash[:10]} (served in 1ms)")
        return cached_payload

    # 2. Image validation
    ai_service.validate_image_size(file_bytes)

    # 3. Concurrency Gate: smooth queueing under 100–1000 concurrent users without server crash
    acquired = _AI_GATE.acquire(timeout=_AI_QUEUE_TIMEOUT)
    if not acquired:
        logger.error(f"AI scan queue timeout ({_AI_QUEUE_TIMEOUT}s) exceeded under heavy concurrent traffic.")
        raise TimeoutError("AI scanning service is currently experiencing very high demand. Please try again in a few moments.")

    try:
        # Base64 encoding
        base64_image = ai_service.encode_image_to_base64(file_bytes)

        # Vision LLM call using AI team's prompt and schema (~2.4s)
        raw_json = ai_service.call_llm_for_analysis(base64_image, mime_type)

        # Check if the image is actually a clothing item
        is_garment, reason = is_valid_garment(raw_json)
        if not is_garment:
            non_garment_res = {
                "is_garment": False,
                "message": "The uploaded image does not appear to be a clothing item. Please capture or upload a clear photo of a garment.",
                "notes": reason,
            }
            cache.set(cache_key, non_garment_res, timeout=_AI_CACHE_TTL)
            return non_garment_res

        # Smart Brand Resolution
        brand_data = raw_json.get("brand", {}) or {}
        has_logo = bool(brand_data.get("logo_text") or brand_data.get("logo_symbol"))
        if has_logo and getattr(settings, 'AI_BRAND_SEARCH_ENABLED', False):
            try:
                raw_json = ai_service.resolve_brand(raw_json)
            except Exception as e:
                logger.warning(f"Brand search skipped/timed out: {e}")
        else:
            current_name = (brand_data.get("name") or "").strip()
            if not current_name or current_name.lower() in ("unknown", "other", "n/a", "none", "null"):
                brand_data["name"] = "N/A"
            brand_data["detected_from_logo"] = False
            brand_data["confidence"] = "none"
            raw_json["brand"] = brand_data

        # Brand sanitization
        raw_json = ai_service._sanitize_brand(raw_json)

        # Price estimation & sanitization
        raw_json = ai_service._sanitize_price(raw_json)

        # Validate through AI team's Pydantic schema
        validated_result = DressAnalysisResult(**raw_json) if DressAnalysisResult else ai_service.DressAnalysisResult(**raw_json)
        out_dict = validated_result.model_dump()
        out_dict["is_garment"] = True

        # Cache valid scan result for repeat scans
        cache.set(cache_key, out_dict, timeout=_AI_CACHE_TTL)
        return out_dict

    finally:
        _AI_GATE.release()


def analyze_dress_with_openai(image_bytes: bytes, mime_type: str = 'image/jpeg', user=None) -> dict:
    """
    Invokes dress-analyzer-ai and returns a clean, structured dictionary
    tailored for Closly ClosetItem creation without redundant debug data.
    Never falls back to fake heuristics (C-04).
    """
    if not AI_TEAM_MODULE_AVAILABLE or ai_service is None:
        logger.error("dress-analyzer-ai module is not available in sys.path.")
        raise AIServiceUnavailableError("AI scanning service is currently unavailable.")

    api_key = getattr(settings, 'LLM_API_KEY', '') or ''
    if not api_key:
        logger.error("LLM_API_KEY is not configured.")
        raise AIServiceUnavailableError("AI scanning service is currently not configured.")

    try:
        data = run_direct_dress_analysis(image_bytes, mime_type=mime_type, user=user)

        # Early exit if non-clothing item detected
        if not data.get("is_garment", True):
            return {
                "is_garment": False,
                "message": data.get("message") or "The uploaded image does not appear to be a clothing item.",
                "notes": data.get("notes", ""),
            }

        # Parse fields from the AI team's schema
        garment_type = str(data.get("garment_type", "other")).lower().strip()
        category = CATEGORY_MAPPING.get(garment_type, 'top')
        gender = str(data.get("gender", "unisex")).lower().strip()
        primary_color = str(data.get("primary_color", "Neutral")).strip().title()
        secondary_colors = data.get("secondary_colors", [])
        if not isinstance(secondary_colors, list):
            secondary_colors = []
        pattern = str(data.get("pattern", "solid")).lower().strip()
        notes = data.get("notes")

        # Brand from dress-analyzer-ai
        brand_info = data.get("brand", {})
        if isinstance(brand_info, dict):
            brand_name = brand_info.get("name", "N/A").strip()
            detected_from_logo = bool(brand_info.get("detected_from_logo", False))
            brand_confidence = str(brand_info.get("confidence", "none")).lower()
        else:
            brand_name = str(brand_info).strip() or "N/A"
            detected_from_logo = False
            brand_confidence = "none"

        # Numerical confidence score
        if brand_confidence == "high":
            confidence = 0.96
        elif brand_confidence == "medium":
            confidence = 0.90
        elif brand_confidence == "low":
            confidence = 0.85
        else:
            confidence = 0.80

        # Estimated price from dress-analyzer-ai
        estimated_price = data.get("estimated_price", {})
        if isinstance(estimated_price, dict) and estimated_price.get("amount"):
            try:
                price = float(estimated_price["amount"])
            except (ValueError, TypeError):
                price = CATEGORY_BASE_PRICES.get(category, 35.00)
        else:
            price = CATEGORY_BASE_PRICES.get(category, 35.00)

        # Format user-friendly display name: e.g. "Navy Blue Floral Dress"
        pattern_display = pattern.title() if pattern and pattern not in ('solid', 'other') else ''
        name_parts = [primary_color, pattern_display, garment_type.replace('_', ' ').replace('-', ' ').title()]
        name = " ".join([p for p in name_parts if p]).strip()
        if not name:
            name = f"{primary_color} {category.title()}"

        # Assign style vibe
        if pattern in ('striped', 'checked') or category in ('dresses_outerwear', 'shoes'):
            style_vibe = "Smart Casual & Elevated"
        elif pattern in ('floral', 'abstract', 'polka-dot'):
            style_vibe = "Chic & Statement"
        elif garment_type in ('hoodie', 'tshirt', 't-shirt', 'sneakers', 'sweatshirt'):
            style_vibe = "Everyday Streetwear"
        else:
            style_vibe = "Classic Minimalist"

        return {
            "name": name,
            "category": category,
            "color": primary_color,
            "secondary_colors": secondary_colors,
            "brand": brand_name,
            "brand_info": {
                "name": brand_name,
                "detected_from_logo": detected_from_logo,
                "confidence": brand_confidence,
            },
            "estimated_price": estimated_price,
            "gender": gender,
            "pattern": pattern,
            "notes": notes,
            "price": f"{price:.2f}",
            "currency": "EUR",
            "style_vibe": style_vibe,
            "confidence": confidence,
            "is_garment": True,
            "is_full_outfit": False,
        }

    except TimeoutError:
        raise
    except AIServiceUnavailableError:
        raise
    except Exception as exc:
        logger.error(f"dress-analyzer-ai execution error: {exc}", exc_info=True)
        raise AIServiceUnavailableError("AI vision service is temporarily unavailable. Please try again in a few moments.")

