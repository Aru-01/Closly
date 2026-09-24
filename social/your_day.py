"""
Your Day Weather & Smart Wardrobe Recommender Engine
Provides:
1. Live meteorological weather data (Open-Meteo free API with zero key dependency).
2. Daily wardrobe outfit suggestion matching today's weather demands from the user's ClosetItems.
3. Personalized stylist description explaining why to wear this look today.
"""

import requests
import logging
from django.utils import timezone
from django.core.cache import cache
from closet.models import ClosetItem
from users.utils import build_absolute_media_url

logger = logging.getLogger(__name__)

WMO_WEATHER_CODES = {
    0: ("Clear Sky", "Sunny & Crisp", "sunny"),
    1: ("Mainly Clear", "Bright & Clear", "partly_cloudy"),
    2: ("Partly Cloudy", "Mild & Pleasant", "partly_cloudy"),
    3: ("Overcast", "Cool & Overcast", "cloudy"),
    45: ("Foggy", "Misty & Atmospheric", "fog"),
    48: ("Depositing Rime Fog", "Cold & Misty", "fog"),
    51: ("Light Drizzle", "Damp & Breezy", "drizzle"),
    53: ("Moderate Drizzle", "Cool & Showery", "drizzle"),
    55: ("Dense Drizzle", "Wet & Chilly", "drizzle"),
    61: ("Slight Rain", "Light Rain Expected", "rain"),
    63: ("Moderate Rain", "Rainy & Damp", "rain"),
    65: ("Heavy Rain", "Heavy Rain & Wet", "rain"),
    71: ("Slight Snow", "Cold & Snowy", "snow"),
    73: ("Moderate Snow", "Winter Chill", "snow"),
    75: ("Heavy Snow", "Heavy Winter Chill", "snow"),
    80: ("Rain Showers", "Scattered Showers", "showers"),
    81: ("Moderate Showers", "Showery & Breezy", "showers"),
    82: ("Violent Showers", "Heavy Downpour", "showers"),
    95: ("Thunderstorm", "Stormy & Wet", "thunderstorm"),
}


def get_live_weather(lat=None, lon=None, city=None, user=None):
    """
    Fetches real-time weather from Open-Meteo (100% free, no API key needed).
    Falls back gracefully to profile city or seasonal estimates if unreachable.
    """
    # Coordinates fallback: Default to London / New York if not provided
    default_lat, default_lon = 51.5074, -0.1278
    city_name = city or "London"

    if lat is not None and lon is not None:
        try:
            target_lat = float(lat)
            target_lon = float(lon)
            city_name = city or getattr(user, 'city', None) or "Current Location"
        except (ValueError, TypeError):
            target_lat, target_lon = default_lat, default_lon
    elif user and getattr(user, 'city', None):
        city_name = user.city
        target_lat, target_lon = default_lat, default_lon
    else:
        target_lat, target_lon = default_lat, default_lon

    cache_key = f"live_weather:{round(target_lat, 2)}:{round(target_lon, 2)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now = timezone.now()
    day_name = now.strftime('%A')
    date_formatted = now.strftime('%d %b %Y')

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={target_lat}&longitude={target_lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,surface_pressure"
            f"&timezone=auto"
        )
        resp = requests.get(url, timeout=3.5)
        if resp.status_code == 200:
            data = resp.json()
            current = data.get('current', {})
            temp_c = round(float(current.get('temperature_2m', 15.0)), 1)
            humidity = int(current.get('relative_humidity_2m', 64))
            wind_kmh = round(float(current.get('wind_speed_10m', 12.0)), 1)
            pressure_mb = int(current.get('surface_pressure', 1012))
            code = int(current.get('weather_code', 2))

            condition, vibe, icon = WMO_WEATHER_CODES.get(code, ("Partly Cloudy", "Mild & Pleasant", "partly_cloudy"))
            weather_result = {
                "day": day_name,
                "date": date_formatted,
                "city": city_name,
                "temp": f"{temp_c:g}°C",
                "temp_val": temp_c,
                "condition": condition,
                "weather_vibe": vibe,
                "humidity": f"{humidity}%",
                "wind": f"{wind_kmh:g} km/h",
                "pressure": f"{pressure_mb} mb",
                "icon": icon,
            }
            cache.set(cache_key, weather_result, timeout=3600)  # Cache for 1 hour (3600 seconds)
            return weather_result
    except Exception as e:
        logger.warning(f"Open-Meteo weather fetch failed: {e}. Using seasonal fallback.")

    # Graceful Fallback
    fallback_result = {
        "day": day_name,
        "date": date_formatted,
        "city": city_name,
        "temp": "15°C",
        "temp_val": 15.0,
        "condition": "Partly Cloudy",
        "weather_vibe": "Mild & Pleasant",
        "humidity": "64%",
        "wind": "12 km/h",
        "pressure": "1012 mb",
        "icon": "partly_cloudy",
    }
    cache.set(cache_key, fallback_result, timeout=3600)
    return fallback_result


import json
from django.conf import settings


def get_ai_daily_outfit_recommendation(user, user_items, weather, request=None):
    """
    Leverages OpenAI GPT-4o as Closly's luxury personal stylist.
    Selects matching items from the user's available wardrobe for today's weather
    and produces an inspiring, tailored styling explanation.
    Rotates items daily to ensure users discover and wear their whole closet.
    """
    api_key = getattr(settings, 'LLM_API_KEY', '') or ''
    if not api_key or not user_items:
        return None

    model = getattr(settings, 'LLM_MODEL', 'gpt-4o') or 'gpt-4o'
    base_url = getattr(settings, 'LLM_BASE_URL', None)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None, timeout=12.0)

        # Extract user preferences if available
        prefs_text = "Casual & Clean"
        if hasattr(user, 'preferences'):
            pref = user.preferences
            style_match = getattr(pref, 'style_match', []) or []
            dress_for = getattr(pref, 'what_do_you_dress_for', []) or []
            parts = []
            if style_match:
                parts.append(f"Style identity: {', '.join(style_match)}")
            if dress_for:
                parts.append(f"Dressing for: {', '.join(dress_for)}")
            if parts:
                prefs_text = "; ".join(parts)

        # Deterministic daily rotation seed to order items for LLM visibility
        now = timezone.now()
        user_num = int(str(user.id).replace('-', '')[:8], 16) if hasattr(user, 'id') and user.id else 0
        day_seed = now.date().toordinal() + user_num

        # Sort items: prioritize least worn and least recently worn
        sorted_items = sorted(
            user_items,
            key=lambda it: (it.times_worn, it.last_worn_at.timestamp() if it.last_worn_at else 0)
        )
        # Apply day offset so different items lead the candidate list across days
        rotation_offset = day_seed % len(sorted_items)
        rotated_candidates = sorted_items[rotation_offset:] + sorted_items[:rotation_offset]

        items_summary = [
            {
                "id": it.id,
                "name": it.name,
                "category": it.category,
                "color": it.color,
                "brand": it.brand,
                "times_worn": it.times_worn
            }
            for it in rotated_candidates[:25]
        ]

        temp = weather.get("temp", "20°C")
        condition = weather.get("condition", "Pleasant")
        vibe = weather.get("weather_vibe", "Mild")
        day_name = weather.get("day", now.strftime('%A'))
        date_str = weather.get("date", now.strftime('%d %b %Y'))

        prompt = f"""You are Closly's luxury AI fashion stylist.
Select the most cohesive and stylish outfit from the user's available digital wardrobe for today's weather.

Date: {day_name}, {date_str}
Today's Weather:
- Temperature: {temp}
- Sky Condition: {condition} ({vibe})

User Style Preferences: {prefs_text}

Available Wardrobe Pieces:
{json.dumps(items_summary, indent=2)}

Stylist Instructions & Rotation Rules:
1. DAILY WARDROBE ROTATION:
   - Ensure the outfit recommendation varies day-to-day.
   - Prioritize pieces that have 0 or few `times_worn` so the user utilizes their whole closet.
   - Never recommend the exact same pieces day after day.
2. HANDLING WARDROBE GAPS:
   - If the user's closet contains multiple categories (top, bottom, shoes, etc.), compose a complete matching look.
   - If the user only has items in ONE category (for example, only tops uploaded), choose today's best featured piece from that category, and in the styling explanation provide personalized advice on what bottoms and shoes to pair with it.
3. WEATHER DEMAND:
   - Cold (<14°C): Prioritize warm pieces, outerwear, jackets, or layering.
   - Rain / Showers / Thunderstorm: Advise on water protection and layering.
   - Warm (>21°C): Prioritize light, breathable tops or dresses.
4. Only select IDs that exist in the provided Available Wardrobe Pieces.

Respond with ONLY valid JSON:
{{
  "selected_item_ids": [1, 2],
  "styling_description": "..."
}}
"""

        response = client.chat.completions.create(
            model=model,
            max_tokens=400,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content.replace("json", "", 1).strip()

        data = json.loads(content)
        selected_ids = data.get("selected_item_ids", [])
        styling_description = data.get("styling_description", "").strip()

        if not selected_ids or not styling_description:
            return None

        # Map back to closet items preserving slot order
        item_map = {it.id: it for it in user_items}
        selected_items = [item_map[i] for i in selected_ids if i in item_map]

        if not selected_items:
            return None

        # Slot classification
        slot_order = ['dresses_outerwear', 'top', 'bottom', 'shoes', 'accessories']
        category_to_slot = {
            'dresses_outerwear': 'outerwear',
            'top': 'top',
            'bottom': 'bottom',
            'shoes': 'shoes',
            'accessories': 'accessories',
            'other': 'accessories'
        }

        outfit_pieces = []
        items_to_record = []
        for cat in slot_order:
            for it in selected_items:
                if it.category == cat and it.id not in items_to_record:
                    items_to_record.append(it.id)
                    outfit_pieces.append({
                        "slot": category_to_slot.get(it.category, "top"),
                        "id": it.id,
                        "name": it.name,
                        "category": it.category,
                        "color": it.color,
                        "brand": it.brand,
                        "price": float(it.price),
                        "times_worn": it.times_worn,
                        "image": build_absolute_media_url(it.image, request=request)
                    })

        for it in selected_items:
            if it.id not in items_to_record:
                items_to_record.append(it.id)
                outfit_pieces.append({
                    "slot": category_to_slot.get(it.category, "top"),
                    "id": it.id,
                    "name": it.name,
                    "category": it.category,
                    "color": it.color,
                    "brand": it.brand,
                    "price": float(it.price),
                    "times_worn": it.times_worn,
                    "image": build_absolute_media_url(it.image, request=request)
                })

        return {
            "pieces": outfit_pieces,
            "styling_description": styling_description,
            "item_ids_for_wear_today": items_to_record,
            "total_pieces_selected": len(outfit_pieces),
        }

    except Exception as e:
        logger.warning(f"Error generating AI daily outfit recommendation: {e}. Falling back to rule engine.")
        return None


def suggest_daily_outfit(user, weather, request=None):
    """
    Selects matching items from the user's online digital wardrobe (ClosetItem)
    tailored to today's temperature and conditions.
    First tries OpenAI GPT-4o Personal Stylist; falls back to deterministic rule engine.
    Ensures smart daily rotation across the user's wardrobe and adapts to single-category wardrobes.
    """
    user_items = list(ClosetItem.objects.filter(user=user))
    if not user_items:
        return {
            "pieces": [],
            "styling_description": "Your digital closet is currently empty. Add your favorite clothes to receive personalized daily outfit recommendations.",
            "item_ids_for_wear_today": [],
            "total_pieces_selected": 0,
        }

    now = timezone.now()
    cache_key = f"daily_outfit_suggestion:{user.id}:{now.strftime('%Y-%m-%d')}"
    cached_suggestion = cache.get(cache_key)
    if cached_suggestion:
        return cached_suggestion

    # 1. Try OpenAI GPT-4o AI Personal Stylist
    ai_suggestion = get_ai_daily_outfit_recommendation(user, user_items, weather, request=request)
    if ai_suggestion:
        cache.set(cache_key, ai_suggestion, timeout=43200)  # 12 hours
        return ai_suggestion

    # 2. Fallback to deterministic temperature-specific wardrobe logic with daily rotation
    temp = weather.get("temp_val", 15.0)
    wind_str = weather.get("wind", "12 km/h")
    condition = weather.get("condition", "Partly Cloudy")

    now = timezone.now()
    user_num = int(str(user.id).replace('-', '')[:8], 16) if hasattr(user, 'id') and user.id else 0
    day_seed = now.date().toordinal() + user_num

    # Segregate by categories in-memory, sorted by least worn then least recently worn
    def sort_items(items):
        return sorted(
            items,
            key=lambda it: (it.times_worn, it.last_worn_at.timestamp() if it.last_worn_at else 0)
        )

    tops = sort_items([it for it in user_items if it.category == 'top'])
    bottoms = sort_items([it for it in user_items if it.category == 'bottom'])
    outerwears = sort_items([it for it in user_items if it.category == 'dresses_outerwear'])
    shoes = sort_items([it for it in user_items if it.category == 'shoes'])
    accessories = sort_items([it for it in user_items if it.category in ['accessories', 'other']])

    # Pick rotated item for each category using day_seed
    def pick_rotated(item_list, offset_extra=0):
        if not item_list:
            return None
        idx = (day_seed + offset_extra) % len(item_list)
        return item_list[idx]

    selected_top = pick_rotated(tops)
    selected_bottom = pick_rotated(bottoms)
    selected_shoes = pick_rotated(shoes)
    selected_acc = pick_rotated(accessories)
    selected_outerwear = None

    # Weather flags
    is_rain = any(w in condition.lower() for w in ['rain', 'drizzle', 'shower', 'storm', 'snow'])
    is_cold = temp < 14.0
    is_mild = 14.0 <= temp <= 21.0
    is_warm = temp > 21.0

    if is_cold:
        # Cold: Outerwear is required if available
        if outerwears:
            selected_outerwear = pick_rotated(outerwears)
        
        top_name = selected_top.name if selected_top else "warm top"
        if selected_bottom:
            bottom_desc = f"with {selected_bottom.name}"
        else:
            bottom_desc = "paired with dark slim jeans or tailored trousers"

        style_reason = (
            f"With temperatures at {temp}°C and {condition.lower()} skies, "
            f"layering is essential for thermal warmth. "
            + (f"Layer your {selected_outerwear.name} over your {top_name} " if selected_outerwear else f"Wear your {top_name} ")
            + f"{bottom_desc} to stay warm, comfortable, and chic."
        )
    elif is_mild:
        # Mild / Breezy: Light layering
        if outerwears and (temp < 18.0 or is_rain):
            selected_outerwear = pick_rotated(outerwears)
        
        top_name = selected_top.name if selected_top else "versatile top"
        if selected_bottom:
            bottom_desc = f"with {selected_bottom.name}"
        else:
            bottom_desc = "paired with your favorite chinos or denim"

        style_reason = (
            f"Today's {temp}°C temperature and {wind_str} breeze call for smart transitional styling. "
            f"Your featured piece today is the {top_name}"
            + (f", layered under the {selected_outerwear.name} " if selected_outerwear else " ")
            + f"{bottom_desc} for the ideal balance of breathability and comfort."
        )
    else:
        # Warm / Hot: Light and breathable
        # In warm weather, a dress from dresses_outerwear can replace top+bottom
        if outerwears and not selected_bottom and not selected_top:
            selected_outerwear = pick_rotated(outerwears)

        top_name = selected_top.name if selected_top else "light cotton piece"
        if selected_bottom:
            bottom_desc = f"paired with {selected_bottom.name}"
        else:
            bottom_desc = "paired with lightweight trousers or shorts"

        style_reason = (
            f"Enjoy the warm {temp}°C weather! "
            f"Your {top_name} {bottom_desc} keeps you cool and effortless all day long."
        )

    # Append rain protection note if applicable
    if is_rain:
        style_reason += " Showers are expected today, so don't forget an umbrella and water-resistant footwear."

    # If the user only has items in 1 category (e.g. only tops or only 1 item), acknowledge wardrobe rotation
    if not selected_bottom and not selected_shoes and not selected_outerwear and selected_top:
        style_reason = (
            f"Today's weather ({temp}°C, {condition.lower()}) highlights your {selected_top.name} "
            f"from {selected_top.brand or 'your closet'}. "
            f"Style this rotating wardrobe staple with clean denim or neutral trousers to complete today's look."
        )

    # Format selected items
    outfit_pieces = []
    items_to_record = []

    for item, slot in [
        (selected_outerwear, "outerwear"),
        (selected_top, "top"),
        (selected_bottom, "bottom"),
        (selected_shoes, "shoes"),
        (selected_acc, "accessories"),
    ]:
        if item and item.id not in items_to_record:
            items_to_record.append(item.id)
            outfit_pieces.append({
                "slot": slot,
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "color": item.color,
                "brand": item.brand,
                "price": float(item.price),
                "times_worn": item.times_worn,
                "image": build_absolute_media_url(item.image, request=request)
            })

    # If user has multiple items but NONE matched the canonical 5 slots, pick the rotated item from whatever is available
    if not outfit_pieces and user_items:
        fallback_item = pick_rotated(sort_items(user_items))
        if fallback_item:
            items_to_record.append(fallback_item.id)
            outfit_pieces.append({
                "slot": "top",
                "id": fallback_item.id,
                "name": fallback_item.name,
                "category": fallback_item.category,
                "color": fallback_item.color,
                "brand": fallback_item.brand,
                "price": float(fallback_item.price),
                "times_worn": fallback_item.times_worn,
                "image": build_absolute_media_url(fallback_item.image, request=request)
            })

    result = {
        "pieces": outfit_pieces,
        "styling_description": style_reason,
        "item_ids_for_wear_today": items_to_record,
        "total_pieces_selected": len(outfit_pieces),
    }
    cache.set(cache_key, result, timeout=43200)  # 12 hours
    return result
