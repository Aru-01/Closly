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
            return {
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
    except Exception as e:
        logger.warning(f"Open-Meteo weather fetch failed: {e}. Using seasonal fallback.")

    # Graceful Fallback
    return {
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


import json
from django.conf import settings


def get_ai_daily_outfit_recommendation(user, user_items, weather, request=None):
    """
    Leverages OpenAI GPT-4o as Closly's luxury personal stylist.
    Selects matching items from the user's available wardrobe for today's weather
    and produces an inspiring, tailored styling explanation.
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

        items_summary = [
            {
                "id": it.id,
                "name": it.name,
                "category": it.category,
                "color": it.color,
                "brand": it.brand,
                "times_worn": it.times_worn
            }
            for it in user_items[:25]
        ]

        temp = weather.get("temp", "20°C")
        condition = weather.get("condition", "Pleasant")
        vibe = weather.get("weather_vibe", "Mild")

        prompt = f"""You are Closly's luxury AI fashion stylist.
Select the most cohesive and stylish outfit from the user's available wardrobe for today's weather.

Today's Weather:
- Temperature: {temp}
- Sky Condition: {condition} ({vibe})

User Style Preferences: {prefs_text}

Available Wardrobe Pieces:
{json.dumps(items_summary, indent=2)}

Guidelines:
1. Select 1 top, 1 bottom, optional outerwear (if temperature is cold or rainy), shoes, and accessories if available.
2. Only select IDs that exist in the provided list.
3. Write an encouraging, chic, 2-3 sentence personalized styling explanation ("styling_description") telling the user why these exact pieces are perfect for today's weather and aesthetic.

Respond with ONLY valid JSON:
{{
  "selected_item_ids": [1, 2],
  "styling_description": "..."
}}
"""

        response = client.chat.completions.create(
            model=model,
            max_tokens=400,
            temperature=0.3,
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
    """
    user_items = list(ClosetItem.objects.filter(user=user))

    # 1. Try OpenAI GPT-4o AI Personal Stylist
    ai_suggestion = get_ai_daily_outfit_recommendation(user, user_items, weather, request=request)
    if ai_suggestion:
        return ai_suggestion

    # 2. Fallback to deterministic temperature-specific wardrobe logic
    temp = weather.get("temp_val", 15.0)
    wind_str = weather.get("wind", "12 km/h")
    condition = weather.get("condition", "Partly Cloudy")

    # Segregate by categories in-memory (1 query instead of 5 separate queries)
    tops = [it for it in user_items if it.category == 'top']
    bottoms = [it for it in user_items if it.category == 'bottom']
    outerwears = [it for it in user_items if it.category == 'dresses_outerwear']
    shoes = [it for it in user_items if it.category == 'shoes']
    accessories = [it for it in user_items if it.category == 'accessories']

    selected_top = tops[0] if tops else None
    selected_bottom = bottoms[0] if bottoms else None
    selected_outerwear = None
    selected_shoes = shoes[0] if shoes else None
    selected_acc = accessories[0] if accessories else None

    # Temperature-specific wardrobe logic
    if temp < 14.0:
        # Cold: Outerwear is required
        if outerwears:
            selected_outerwear = outerwears[0]
        style_reason = (
            f"With temperatures at {temp}°C and {condition.lower()} skies, "
            f"layering is essential for thermal warmth. "
            f"A structured coat or jacket layered over your {selected_top.name if selected_top else 'top'} "
            f"with durable {selected_bottom.name if selected_bottom else 'trousers'} will keep you warm, comfortable, and chic."
        )
    elif 14.0 <= temp <= 21.0:
        # Mild / Breezy: Light layering (blazer or jacket)
        if outerwears:
            selected_outerwear = outerwears[0]
        style_reason = (
            f"Today's {temp}°C temperature and {wind_str} breeze call for smart transitional styling. "
            f"Pairing your {selected_top.name if selected_top else 'favorite top'} "
            + (f"under your {selected_outerwear.name} " if selected_outerwear else "")
            + f"with {selected_bottom.name if selected_bottom else 'tailored bottoms'} offers the perfect balance of breathability and light wind protection."
        )
    else:
        # Warm / Hot: Light and breathable
        style_reason = (
            f"Enjoy the warm {temp}°C weather! "
            f"A light, breathable {selected_top.name if selected_top else 'cotton top'} "
            f"paired with {selected_bottom.name if selected_bottom else 'comfortable bottoms'} "
            f"keeps you cool and effortless all day long."
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
        if item:
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

    return {
        "pieces": outfit_pieces,
        "styling_description": style_reason,
        "item_ids_for_wear_today": items_to_record,
        "total_pieces_selected": len(outfit_pieces),
    }
