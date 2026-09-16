import base64
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# Official prompt designed by Closly AI team (dress-analyzer-ai)
ANALYSIS_PROMPT = """You are a fashion image analysis expert. Carefully examine this dress image and respond according to the JSON schema below. Return ONLY valid JSON — no extra text, explanation, or markdown code fences.

JSON schema:
{
  "garment_type": "tshirt | shirt | pant | plazoo | jeans | saree | kurti | dress | skirt | jacket | shoes | accessories | other",
  "gender": "male | female | unisex",
  "primary_color": "string",
  "secondary_colors": ["string"],
  "pattern": "solid | striped | checked | floral | printed | polka-dot | abstract | other",
  "brand": {
    "name": "string",
    "detected_from_logo": true/false,
    "confidence": "high | medium | low | assumed"
  },
  "notes": "string (mention here if any field is an assumption rather than a confident detection)"
}

Rules:
- If you are not fully certain about any field, give your best guess but lower the confidence to "low" or "assumed".
- For brand: NEVER return "Unknown", "N/A", or leave it empty. If a logo is clearly visible, give the correct brand name, set confidence to "high" or "medium", and set detected_from_logo to true. If no logo is visible or identifiable, infer the most plausible real-world brand based on the garment's style, cut, fabric, stitching pattern, and overall design — pick a well-known brand commonly associated with that style — set confidence to "assumed" and detected_from_logo to false. The brand.name field must never be blank or "Unknown".
- Return only valid JSON, nothing else.
"""

# Map fine-grained garment types to Closly's core category taxonomy
CATEGORY_MAPPING = {
    'tshirt': 'top',
    't-shirt': 'top',
    'shirt': 'top',
    'kurti': 'top',
    'top': 'top',
    'hoodie': 'top',
    'sweater': 'top',
    'blouse': 'top',
    'polo': 'top',
    'pant': 'bottom',
    'pants': 'bottom',
    'plazoo': 'bottom',
    'palazzo': 'bottom',
    'jeans': 'bottom',
    'trousers': 'bottom',
    'shorts': 'bottom',
    'skirt': 'bottom',
    'dress': 'dresses_outerwear',
    'saree': 'dresses_outerwear',
    'sari': 'dresses_outerwear',
    'jacket': 'dresses_outerwear',
    'coat': 'dresses_outerwear',
    'blazer': 'dresses_outerwear',
    'outerwear': 'dresses_outerwear',
    'shoes': 'shoes',
    'sneakers': 'shoes',
    'boots': 'shoes',
    'heels': 'shoes',
    'sandals': 'shoes',
    'footwear': 'shoes',
    'accessories': 'accessories',
    'accessory': 'accessories',
    'bag': 'accessories',
    'handbag': 'accessories',
    'hat': 'accessories',
    'cap': 'accessories',
    'watch': 'accessories',
    'belt': 'accessories',
    'other': 'other',
}

# Standard realistic baseline prices by category
CATEGORY_BASE_PRICES = {
    'top': 35.00,
    'bottom': 55.00,
    'dresses_outerwear': 89.00,
    'shoes': 75.00,
    'accessories': 28.00,
    'other': 30.00,
}


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode raw image bytes to a base64 UTF-8 string."""
    return base64.b64encode(image_bytes).decode('utf-8')


def validate_image_size(image_bytes: bytes, max_mb: int = 5):
    """Raise ValueError if image size exceeds allowed threshold."""
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > max_mb:
        raise ValueError(f"Image too large: {size_mb:.2f} MB (Limit: {max_mb} MB)")


def analyze_dress_with_openai(image_bytes: bytes, mime_type: str = 'image/jpeg') -> dict | None:
    """
    Directly ports and executes the Closly AI team's OpenAI Vision model
    from dress-analyzer-ai within the Django backend.
    
    Returns a unified metadata dictionary compatible with Closly ClosetItem,
    or None if LLM is unavailable or encounters an error (enabling fallback).
    """
    api_key = getattr(settings, 'LLM_API_KEY', '') or ''
    if not api_key:
        logger.info("LLM_API_KEY is not set. Skipping OpenAI Vision analysis.")
        return None

    model = getattr(settings, 'LLM_MODEL', 'gpt-4o') or 'gpt-4o'
    base_url = getattr(settings, 'LLM_BASE_URL', None)
    max_mb = getattr(settings, 'MAX_IMAGE_SIZE_MB', 5)

    try:
        validate_image_size(image_bytes, max_mb=max_mb)
    except ValueError as val_err:
        logger.warning(f"AI image validation error: {val_err}")
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None, timeout=25.0)

        base64_image = encode_image_to_base64(image_bytes)

        response = client.chat.completions.create(
            model=model,
            max_tokens=600,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        },
                        {
                            "type": "text",
                            "text": ANALYSIS_PROMPT
                        }
                    ]
                }
            ]
        )

        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.startswith("json"):
                raw_text = raw_text.replace("json", "", 1).strip()

        data = json.loads(raw_text)

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

        brand_info = data.get("brand", {})
        if isinstance(brand_info, dict):
            brand_name = brand_info.get("name", "N/A").strip()
            detected_from_logo = bool(brand_info.get("detected_from_logo", False))
            brand_confidence = str(brand_info.get("confidence", "assumed")).lower()
        else:
            brand_name = str(brand_info).strip() or "N/A"
            detected_from_logo = False
            brand_confidence = "assumed"

        # Determine numerical confidence score for Closly UI
        if brand_confidence == "high":
            confidence = 0.96
        elif brand_confidence == "medium":
            confidence = 0.90
        else:
            confidence = 0.85

        # Format user-friendly name: e.g. "Navy Blue Striped Shirt"
        pattern_display = pattern.title() if pattern and pattern not in ('solid', 'other') else ''
        name_parts = [primary_color, pattern_display, garment_type.replace('_', ' ').title()]
        name = " ".join([p for p in name_parts if p]).strip()
        if not name:
            name = f"{primary_color} {category.title()}"

        # Assign style vibe
        if pattern in ('striped', 'checked') or category in ('dresses_outerwear', 'shoes'):
            style_vibe = "Smart Casual & Elevated"
        elif pattern in ('floral', 'abstract', 'polka-dot'):
            style_vibe = "Chic & Statement"
        elif garment_type in ('hoodie', 'tshirt', 'sneakers'):
            style_vibe = "Everyday Streetwear"
        else:
            style_vibe = "Classic Minimalist"

        price = CATEGORY_BASE_PRICES.get(category, 45.00)

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
            "gender": gender,
            "pattern": pattern,
            "notes": notes,
            "price": f"{price:.2f}",
            "style_vibe": style_vibe,
            "confidence": confidence,
            "is_full_outfit": False,
            "detected_items": [{
                "slot": category,
                "category": category,
                "name": name,
                "color": primary_color,
                "brand": brand_name,
                "price": f"{price:.2f}",
                "style_vibe": style_vibe,
                "confidence": confidence,
            }],
            "total_pieces_detected": 1,
            "ai_engine": f"OpenAI GPT-4o Vision ({model})",
            "ai_raw_analysis": data,
        }

    except Exception as exc:
        logger.warning(f"OpenAI dress analyzer error: {exc}. Will fallback to heuristic engine.", exc_info=True)
        return None
