import base64
import json
from fastapi import UploadFile
from llm_client import llm_client
from config import settings
from schemas import DressAnalysisResult
from apify_client_wrapper import search_brand_from_logo_text


ANALYSIS_PROMPT = """You are a professional fashion AI stylist and garment analysis expert. Carefully examine this garment image and respond strictly according to the JSON schema below. Return ONLY valid JSON — no markdown code fences, no conversational filler.

JSON schema:
{
  "is_garment": true,
  "garment_type": "t-shirt | shirt | polo | blouse | sweater | hoodie | sweatshirt | cardigan | blazer | suit | jacket | coat | jeans | pants | trousers | shorts | skirt | dress | jumpsuit | sneakers | boots | shoes | loafers | sandals | heels | bag | handbag | backpack | hat | cap | beanie | belt | scarf | sunglasses | watch | jewelry | accessory | other",
  "gender": "male | female | unisex",
  "primary_color": "string",
  "secondary_colors": ["string"],
  "pattern": "solid | striped | checked | floral | printed | polka-dot | abstract | graphic | other",
  "brand": {
    "name": "string",
    "detected_from_logo": true,
    "confidence": "high | medium | low | none",
    "logo_text": "string or null",
    "logo_symbol": "string or null"
  },
  "estimated_price": {
    "currency": "EUR",
    "amount": number,
    "range_min": number,
    "range_max": number,
    "confidence": "high | medium | low"
  },
  "notes": "string"
}

Critical Classification Rules:
1. is_garment (BOOLEAN):
   - Set to true if the image depicts wearable clothing, footwear, headwear, bags, or wearable fashion accessories.
   - Graphic t-shirts, printed hoodies, patterned dresses, or illustrated garments ARE valid wearable garments (set is_garment: true).
   - Set to false ONLY if the image depicts a screenshot, text document, meme, landscape, food, animal, electronics, or non-wearable artwork/object.
2. brand.name:
   - Provide the brand name ONLY if a physical brand logo, brand tag, or legible brand wordmark is visible on the garment.
   - If no brand logo or brand text is clearly identifiable, set "name": "N/A", "confidence": "none", "detected_from_logo": false.
   - NEVER invent, hallucinate, or guess brand names when no brand markings exist.
3. estimated_price:
   - Estimate realistic EUR (€) retail pricing based on garment type, fabric weight, and silhouette.
   - Currency MUST be "EUR".
"""


INVALID_BRAND_VALUES = {"", "other", "unknown", "none", "null", "undefined"}

DEFAULT_PRICE_BY_GARMENT = {
    "t-shirt": (25, 15, 45),
    "shirt": (45, 25, 80),
    "polo": (35, 20, 65),
    "blouse": (40, 25, 75),
    "sweater": (55, 30, 95),
    "hoodie": (50, 30, 90),
    "sweatshirt": (45, 25, 80),
    "cardigan": (50, 30, 85),
    "blazer": (95, 55, 180),
    "suit": (180, 90, 350),
    "jacket": (85, 45, 160),
    "coat": (120, 60, 240),
    "jeans": (60, 35, 110),
    "pants": (55, 30, 95),
    "trousers": (60, 35, 110),
    "shorts": (35, 20, 60),
    "skirt": (40, 20, 75),
    "dress": (65, 35, 130),
    "jumpsuit": (75, 40, 140),
    "sneakers": (85, 45, 150),
    "boots": (110, 60, 200),
    "shoes": (75, 40, 130),
    "loafers": (80, 45, 140),
    "sandals": (45, 25, 80),
    "heels": (75, 40, 130),
    "bag": (65, 30, 140),
    "handbag": (85, 40, 180),
    "backpack": (55, 30, 100),
    "hat": (25, 15, 40),
    "cap": (25, 15, 40),
    "beanie": (20, 10, 35),
    "belt": (30, 15, 55),
    "scarf": (25, 15, 45),
    "sunglasses": (45, 20, 100),
    "watch": (95, 40, 220),
    "jewelry": (35, 15, 80),
    "accessory": (25, 10, 50),
    "other": (35, 20, 60),
}


def encode_image_to_base64(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("utf-8")


def validate_image_size(file_bytes: bytes):
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.MAX_IMAGE_SIZE_MB:
        raise ValueError(f"Image too large: {size_mb:.2f} MB (Limit: {settings.MAX_IMAGE_SIZE_MB} MB)")


def call_llm_for_analysis(base64_image: str, mime_type: str) -> dict:
    from llm_client import get_llm_client
    client = get_llm_client()
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        max_tokens=700,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
                    {"type": "text", "text": ANALYSIS_PROMPT}
                ]
            }
        ]
    )

    raw_text = response.choices[0].message.content.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    return json.loads(raw_text)



def _google_top_result(query_text: str) -> dict | None:
    """Runs the Apify Google search and returns the top organic result dict, or None."""
    try:
        results = search_brand_from_logo_text(query_text)
    except Exception:
        return None

    if not results:
        return None

    organic_results = results[0].get("organicResults", [])
    if not organic_results:
        return None

    return organic_results[0]  # contains at least "title", possibly "description"/"url"


def _looks_like_brand_name(title: str) -> bool:
    """
    Very lightweight sanity check so we don't blindly accept junk page titles
    (e.g. "10 Best T-Shirts of 2026 - Buying Guide") as a brand name.
    """
    if not title:
        return False
    bad_markers = ["best", "top 10", "buying guide", "review", "how to", "vs", "wikipedia"]
    lowered = title.lower()
    if any(marker in lowered for marker in bad_markers):
        return False
    if len(title.split()) > 6:
        return False
    return True


def resolve_brand(raw_json: dict) -> dict:
    brand_data = raw_json.get("brand", {}) or {}
    logo_text = brand_data.get("logo_text")
    logo_symbol = brand_data.get("logo_symbol")

    # If external brand search is disabled by configuration (C-03 privacy/cost posture)
    if not getattr(settings, 'AI_BRAND_SEARCH_ENABLED', False):
        if logo_text:
            brand_data["name"] = str(logo_text).strip()
            brand_data["confidence"] = "medium"
            brand_data["detected_from_logo"] = True
        elif not brand_data.get("name") or brand_data.get("name").lower() in INVALID_BRAND_VALUES:
            brand_data["name"] = "N/A"
            brand_data["confidence"] = "none"
            brand_data["detected_from_logo"] = False
        raw_json["brand"] = brand_data
        return raw_json

    # External Apify Google Search (Only if explicitly enabled via AI_BRAND_SEARCH_ENABLED=True)
    if logo_text:
        top_result = _google_top_result(f'"{logo_text}" clothing brand')
        if top_result and _looks_like_brand_name(top_result.get("title", "")):
            brand_data["name"] = top_result["title"]
            brand_data["confidence"] = "high"
            brand_data["detected_from_logo"] = True
            raw_json["brand"] = brand_data
            return raw_json
        brand_data["name"] = str(logo_text).strip()
        brand_data["confidence"] = "medium"
        brand_data["detected_from_logo"] = True
        raw_json["brand"] = brand_data
        return raw_json

    if logo_symbol:
        top_result = _google_top_result(f"{logo_symbol} clothing brand logo")
        if top_result and _looks_like_brand_name(top_result.get("title", "")):
            brand_data["name"] = top_result["title"]
            brand_data["confidence"] = "medium"
            brand_data["detected_from_logo"] = True
            raw_json["brand"] = brand_data
            return raw_json
        brand_data["name"] = "N/A"
        brand_data["confidence"] = "none"
        brand_data["detected_from_logo"] = False
        raw_json["brand"] = brand_data
        return raw_json

    # No logo or brand markings visible
    brand_data["name"] = "N/A"
    brand_data["confidence"] = "none"
    brand_data["detected_from_logo"] = False
    raw_json["brand"] = brand_data
    return raw_json


def _sanitize_brand(raw_json: dict) -> dict:
    """Final safety net — guarantees brand.name is strictly 'N/A' when not verified from a visible logo."""
    brand_data = raw_json.get("brand", {}) or {}
    name = (brand_data.get("name") or "").strip()
    if not name or name.lower() in INVALID_BRAND_VALUES:
        brand_data["name"] = "N/A"
        brand_data["confidence"] = "none"
        brand_data["detected_from_logo"] = False
    raw_json["brand"] = brand_data
    return raw_json


def _sanitize_price(raw_json: dict) -> dict:
    price = raw_json.get("estimated_price")
    garment_type = (raw_json.get("garment_type") or "other").lower()
    default_amount, default_min, default_max = DEFAULT_PRICE_BY_GARMENT.get(
        garment_type, DEFAULT_PRICE_BY_GARMENT["other"]
    )

    if not price or not isinstance(price, dict):
        raw_json["estimated_price"] = {
            "currency": "EUR",
            "amount": float(default_amount),
            "range_min": float(default_min),
            "range_max": float(default_max),
            "confidence": "medium",
        }
        return raw_json

    price.setdefault("currency", "EUR")
    price.setdefault("amount", float(default_amount))
    price.setdefault("range_min", float(default_min))
    price.setdefault("range_max", float(default_max))
    price.setdefault("confidence", "medium")
    raw_json["estimated_price"] = price
    return raw_json



async def analyze_dress_image(file: UploadFile) -> DressAnalysisResult:
    file_bytes = await file.read()
    validate_image_size(file_bytes)

    mime_type = file.content_type or "image/jpeg"
    base64_image = encode_image_to_base64(file_bytes)

    raw_json = call_llm_for_analysis(base64_image, mime_type)

    raw_json = resolve_brand(raw_json)
    raw_json = _sanitize_brand(raw_json)
    raw_json = _sanitize_price(raw_json)

    result = DressAnalysisResult(**raw_json)
    return result