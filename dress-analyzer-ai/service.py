import base64
import json
from fastapi import UploadFile
from llm_client import llm_client
from config import settings
from schemas import DressAnalysisResult
from apify_client_wrapper import search_brand_from_logo_text


ANALYSIS_PROMPT = """You are a fashion image analysis expert. Carefully examine this dress image and respond according to the JSON schema below. Return ONLY valid JSON — no extra text, explanation, or markdown code fences.

JSON schema:
{
  "garment_type": "tshirt | shirt | pant | plazoo | jeans | saree | kurti | dress | skirt | jacket | other",
  "gender": "male | female | unisex",
  "primary_color": "string",
  "secondary_colors": ["string"],
  "pattern": "solid | striped | checked | floral | printed | polka-dot | abstract | other",
  "brand": {
    "name": "string",
    "detected_from_logo": true/false,
    "confidence": "high | medium | low | assumed",
    "logo_text": "string or null",
    "logo_symbol": "string or null"
  },
  "estimated_price": {
    "currency": "USD",
    "amount": number,
    "range_min": number,
    "range_max": number,
    "confidence": "high | medium | low | assumed"
  },
  "notes": "string"
}

Rules for logo_text vs logo_symbol:
- "logo_text": literal readable letters/words physically visible on the garment. Null if none.
- "logo_symbol": a described icon/graphic shape logo with no letters (e.g. "diamond shape", "checkmark swoosh"). Describe ONLY the shape/geometry you see — do not name a brand here, and do not guess a brand in "brand.name" based on a vague shape unless you are genuinely highly confident.

Rules for brand.name:
- Provide your best guess, but be conservative: only claim a specific famous brand if you are genuinely confident, not just because a shape loosely resembles something.
- Never return "other", "unknown", "N/A", or leave it blank.

Rules for estimated_price (MANDATORY — always fill):
- Estimate a realistic USD retail price based on garment type, fabric/build quality, and design complexity.
- Must vary by garment — never a fixed default number.

Return only valid JSON, nothing else — both "brand" and "estimated_price" objects are required.
"""


INVALID_BRAND_VALUES = {"", "other", "unknown", "n/a", "none", "null"}

DEFAULT_PRICE_BY_GARMENT = {
    "tshirt": (12, 8, 25),
    "shirt": (30, 18, 55),
    "pant": (35, 20, 70),
    "jeans": (45, 25, 90),
    "plazoo": (25, 15, 45),
    "saree": (60, 30, 150),
    "kurti": (28, 15, 60),
    "dress": (40, 20, 90),
    "skirt": (28, 15, 55),
    "jacket": (65, 35, 140),
    "other": (30, 15, 60),
}


def encode_image_to_base64(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("utf-8")


def validate_image_size(file_bytes: bytes):
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.MAX_IMAGE_SIZE_MB:
        raise ValueError(f"Image too large: {size_mb:.2f} MB (Limit: {settings.MAX_IMAGE_SIZE_MB} MB)")


def call_llm_for_analysis(base64_image: str, mime_type: str) -> dict:
    response = llm_client.chat.completions.create(
        model=settings.LLM_MODEL,
        max_tokens=700,
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
        raw_text = raw_text.replace("json", "", 1).strip()

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

    # Case 1: literal text visible — most reliable, verify via search
    if logo_text:
        top_result = _google_top_result(f'"{logo_text}" clothing brand logo')
        if top_result and _looks_like_brand_name(top_result.get("title", "")):
            brand_data["name"] = top_result["title"]
            brand_data["confidence"] = "high"
            brand_data["detected_from_logo"] = True
            raw_json["brand"] = brand_data
            return raw_json
        # search inconclusive but text was clearly readable — keep LLM's literal reading
        brand_data["confidence"] = "medium"
        raw_json["brand"] = brand_data
        return raw_json

    # Case 2: only a shape/symbol was seen — do NOT trust the LLM's own brand guess blindly
    if logo_symbol:
        top_result = _google_top_result(f"{logo_symbol} clothing brand logo")
        if top_result and _looks_like_brand_name(top_result.get("title", "")):
            brand_data["name"] = top_result["title"]
            brand_data["confidence"] = "medium"
            brand_data["detected_from_logo"] = True
            raw_json["brand"] = brand_data
            return raw_json

        # Search didn't confidently confirm anything — drop the LLM's specific guess
        # (avoids wrongly saying "Nike"/"Lotto" for a local/unrelated logo)
        fallback_query = f"{logo_symbol} logo generic apparel brand"
        fallback_result = _google_top_result(fallback_query)
        if fallback_result and _looks_like_brand_name(fallback_result.get("title", "")):
            brand_data["name"] = fallback_result["title"]
        else:
            brand_data["name"] = f"Unbranded ({logo_symbol} logo)"
        brand_data["confidence"] = "low"
        brand_data["detected_from_logo"] = False
        raw_json["brand"] = brand_data
        return raw_json

    # Case 3: no logo/text/symbol at all — best-effort related name via garment attributes
    garment_type = raw_json.get("garment_type", "garment")
    color = raw_json.get("primary_color", "")
    pattern = raw_json.get("pattern", "")
    style_query = f"{color} {pattern} {garment_type} popular clothing brand".strip()

    style_result = _google_top_result(style_query)
    if style_result and _looks_like_brand_name(style_result.get("title", "")):
        brand_data["name"] = style_result["title"]
        brand_data["confidence"] = "assumed"
    else:
        brand_data["name"] = f"Generic {garment_type.capitalize()} Brand"
        brand_data["confidence"] = "assumed"

    brand_data["detected_from_logo"] = False
    raw_json["brand"] = brand_data
    return raw_json


def _sanitize_brand(raw_json: dict) -> dict:
    """Final safety net — guarantees brand.name is never blank/invalid, no matter what happened above."""
    brand_data = raw_json.get("brand", {}) or {}
    name = (brand_data.get("name") or "").strip()
    if name.lower() in INVALID_BRAND_VALUES:
        garment_type = raw_json.get("garment_type", "garment")
        brand_data["name"] = f"Generic {garment_type.capitalize()} Brand"
        brand_data["confidence"] = "assumed"
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
            "currency": "USD",
            "amount": default_amount,
            "range_min": default_min,
            "range_max": default_max,
            "confidence": "assumed",
        }
        return raw_json

    price.setdefault("currency", "USD")
    price.setdefault("amount", default_amount)
    price.setdefault("range_min", default_min)
    price.setdefault("range_max", default_max)
    price.setdefault("confidence", "assumed")
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