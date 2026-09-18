import base64
import json
import logging

logger = logging.getLogger(__name__)


def call_gemini_vision_api(image_bytes, mime_type, api_key):
    """
    Calls Google Gemini 1.5 Flash Vision REST endpoint.
    Accurately detects both single garments and multi-item full-body outfits.
    Strictly outputs brand='N/A' unless a brand logo or wordmark is visibly recognizable.
    DO NOT hallucinate caps or shoes if not visible or cropped.
    """
    try:
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        base64_data = base64.b64encode(image_bytes).decode('utf-8')

        prompt = (
            "You are a professional AI fashion stylist and garment detection assistant for Closly. "
            "Analyze this photo carefully. The photo may show EITHER a single garment OR a full-body outfit worn by a person "
            "(e.g., top/shirt, bottom/pants, belt, handbag/accessories, shoes). "
            "STRICT RULES:\n"
            "1. BRAND: You MUST return 'N/A' for brand unless an authentic, recognizable brand logo or label is clearly visible.\n"
            "2. HEADWEAR: DO NOT hallucinate a cap or hat if the subject is not wearing one (natural hair is NOT headwear).\n"
            "3. SHOES: DO NOT hallucinate shoes if the feet/shoes are cropped out of the frame.\n"
            "4. ACCESSORIES & STYLING PIECES: Detect all distinct wearable fashion elements present, including belts (e.g. leather belt with buckle), handbags, tote bags, wristwatches, jewelry, or eyewear. Map their category to 'accessories'.\n"
            "Output ONLY a valid JSON object (no markdown, no backticks) with keys: "
            "'is_full_outfit' (boolean), "
            "'detected_items' (list of visible pieces: 'slot' ['top'|'bottom'|'shoes'|'accessories'|'headwear'], "
            "'name' [fashionable descriptive title, e.g. 'Classic Striped Shirt', 'Pleated Wide-Leg Trousers', 'Brown Leather Belt', 'Green Leather Handbag'], "
            "'category' ['top'|'bottom'|'shoes'|'dresses_outerwear'|'accessories'|'other'], "
            "'color' [dominant color], 'brand' ['N/A' or verified visible brand], 'price' [estimated USD numeric string], 'confidence' [float 0.85-0.99]), "
            "'name' (name of the primary garment or dominant top), "
            "'category' (category of the primary garment), "
            "'color' (dominant primary color), "
            "'brand' ('N/A' or verified visible brand), "
            "'price' (estimated price in USD numeric string), "
            "'style_vibe' (e.g. 'Smart Casual', 'Chic Elegance'), "
            "'confidence' (float between 0.85 and 0.99)."
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.15,
                "maxOutputTokens": 512
            }
        }

        response = requests.post(url, json=payload, timeout=8)
        if response.status_code == 200:
            result = response.json()
            raw_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json", "", 1).strip()
            parsed = json.loads(raw_text)

            valid_categories = {'top', 'bottom', 'shoes', 'dresses_outerwear', 'accessories', 'other'}
            cat = str(parsed.get('category', 'top')).lower()
            if cat not in valid_categories:
                cat = 'top'

            # Clean and sanitize brand
            raw_brand = str(parsed.get('brand', 'N/A')).strip()
            if not raw_brand or raw_brand.lower() in ('unknown', 'none', 'generic', 'unbranded', 'n/a', 'null'):
                brand = 'N/A'
            else:
                brand = raw_brand

            is_full_outfit = bool(parsed.get('is_full_outfit', False))
            detected_items = parsed.get('detected_items', [])

            sanitized_items = []
            if isinstance(detected_items, list):
                for item in detected_items:
                    item_cat = str(item.get('category', 'top')).lower()
                    if item_cat not in valid_categories:
                        name_lower = str(item.get('name', '')).lower()
                        if any(w in name_lower for w in ('belt', 'bag', 'watch', 'glass', 'jewel', 'hat', 'cap', 'scarf')):
                            item_cat = 'accessories'
                        else:
                            item_cat = 'other'
                    item_brand = str(item.get('brand', 'N/A')).strip()
                    if not item_brand or item_brand.lower() in ('unknown', 'none', 'generic', 'n/a', 'null'):
                        item_brand = 'N/A'
                    sanitized_items.append({
                        "slot": str(item.get('slot', item_cat)),
                        "category": item_cat,
                        "name": str(item.get('name', 'Garment Piece')),
                        "color": str(item.get('color', 'Neutral')),
                        "brand": item_brand,
                        "price": str(item.get('price', '35.00')),
                        "style_vibe": str(item.get('style_vibe', parsed.get('style_vibe', 'Casual'))),
                        "confidence": float(item.get('confidence', parsed.get('confidence', 0.95))),
                    })

            if not sanitized_items:
                sanitized_items = [{
                    "slot": cat,
                    "category": cat,
                    "name": str(parsed.get('name', 'Fashion Garment')),
                    "color": str(parsed.get('color', 'Multi-color')),
                    "brand": brand,
                    "price": str(parsed.get('price', '35.00')),
                    "style_vibe": str(parsed.get('style_vibe', 'Casual')),
                    "confidence": float(parsed.get('confidence', 0.95)),
                }]

            return {
                "is_full_outfit": is_full_outfit,
                "detected_items": sanitized_items,
                "total_pieces_detected": len(sanitized_items),
                "name": str(parsed.get('name', sanitized_items[0]['name'])),
                "category": cat,
                "color": str(parsed.get('color', sanitized_items[0]['color'])),
                "brand": brand,
                "price": str(parsed.get('price', sanitized_items[0]['price'])),
                "style_vibe": str(parsed.get('style_vibe', 'Casual')),
                "confidence": float(parsed.get('confidence', 0.95)),
            }
    except Exception as e:
        logger.warning(f"Gemini Vision API call failed: {e}. Falling back to internal engine.")
    return None
