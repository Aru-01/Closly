"""
Your Day Weather & Smart Wardrobe Recommender Engine.
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

DACH_CITY_CENTROIDS = {
    'munich': (48.14, 11.58),
    'münchen': (48.14, 11.58),
    'berlin': (52.52, 13.40),
    'hamburg': (53.55, 10.00),
    'frankfurt': (50.11, 8.68),
    'frankfurt am main': (50.11, 8.68),
    'cologne': (50.94, 6.96),
    'köln': (50.94, 6.96),
    'stuttgart': (48.78, 9.18),
    'düsseldorf': (51.22, 6.78),
    'dusseldorf': (51.22, 6.78),
    'vienna': (48.21, 16.37),
    'wien': (48.21, 16.37),
    'zurich': (47.38, 8.54),
    'zürich': (47.38, 8.54),
    'london': (51.51, -0.13),
    'paris': (48.86, 2.35),
    'new york': (40.71, -74.01),
}


def get_live_weather(lat=None, lon=None, city=None, user=None):
    """
    Fetches real-time weather from Open-Meteo.
    Requires client coordinates or maps known city centroids.
    Returns None if location is unknown rather than defaulting to London (SR-06, SR-20).
    """
    target_lat = None
    target_lon = None
    city_name = city or getattr(user, 'city', None) or "Current Location"

    if lat is not None and lon is not None:
        try:
            target_lat = round(float(lat), 2)
            target_lon = round(float(lon), 2)
            city_name = city or getattr(user, 'city', None) or "Current Location"
        except (ValueError, TypeError):
            target_lat, target_lon = None, None

    if target_lat is None or target_lon is None:
        candidate_city = (city or getattr(user, 'city', '') or '').strip().lower()
        if candidate_city in DACH_CITY_CENTROIDS:
            target_lat, target_lon = DACH_CITY_CENTROIDS[candidate_city]
            city_name = city or user.city

    if target_lat is None or target_lon is None:
        return None

    cache_key = f"live_weather:{target_lat}:{target_lon}"
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
            cache.set(cache_key, weather_result, timeout=3600)
            return weather_result
    except Exception as e:
        logger.warning(f"Open-Meteo weather fetch failed: {e}. Using seasonal fallback.")

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


def suggest_daily_outfit(user, weather, request=None):
    """
    Selects matching items from the user's online digital wardrobe (ClosetItem)
    tailored to today's temperature and conditions.
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

    temp = weather.get("temp_val", 18.0) if weather else 18.0
    wind_str = weather.get("wind", "12 km/h") if weather else "12 km/h"
    condition = weather.get("condition", "Partly Cloudy") if weather else "Mild & Pleasant"

    user_num = int(str(user.id).replace('-', '')[:8], 16) if hasattr(user, 'id') and user.id else 0
    day_seed = now.date().toordinal() + user_num

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

    is_rain = any(w in condition.lower() for w in ['rain', 'drizzle', 'shower', 'storm', 'snow'])
    is_cold = temp < 14.0
    is_mild = 14.0 <= temp <= 21.0

    if is_cold:
        if outerwears:
            selected_outerwear = pick_rotated(outerwears)
        top_name = selected_top.name if selected_top else "warm top"
        bottom_desc = f"with {selected_bottom.name}" if selected_bottom else "paired with dark slim jeans or tailored trousers"
        style_reason = (
            f"With temperatures at {temp}°C and {condition.lower()} skies, "
            f"layering is essential for thermal warmth. "
            + (f"Layer your {selected_outerwear.name} over your {top_name} " if selected_outerwear else f"Wear your {top_name} ")
            + f"{bottom_desc} to stay warm, comfortable, and chic."
        )
    elif is_mild:
        if outerwears and (temp < 18.0 or is_rain):
            selected_outerwear = pick_rotated(outerwears)
        top_name = selected_top.name if selected_top else "versatile top"
        bottom_desc = f"with {selected_bottom.name}" if selected_bottom else "paired with your favorite chinos or denim"
        style_reason = (
            f"Today's {temp}°C temperature and {wind_str} breeze call for smart transitional styling. "
            f"Your featured piece today is the {top_name}"
            + (f", layered under the {selected_outerwear.name} " if selected_outerwear else " ")
            + f"{bottom_desc} for the ideal balance of breathability and comfort."
        )
    else:
        if outerwears and not selected_bottom and not selected_top:
            selected_outerwear = pick_rotated(outerwears)
        top_name = selected_top.name if selected_top else "light cotton piece"
        bottom_desc = f"paired with {selected_bottom.name}" if selected_bottom else "paired with lightweight trousers or shorts"
        style_reason = (
            f"Enjoy the warm {temp}°C weather! "
            f"Your {top_name} {bottom_desc} keeps you cool and effortless all day long."
        )

    if is_rain:
        style_reason += " Showers are expected today, so don't forget an umbrella and water-resistant footwear."

    if not selected_bottom and not selected_shoes and not selected_outerwear and selected_top:
        style_reason = (
            f"Today's weather ({temp}°C, {condition.lower()}) highlights your {selected_top.name} "
            f"from {selected_top.brand or 'your closet'}. "
            f"Style this rotating wardrobe staple with clean denim or neutral trousers to complete today's look."
        )

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
    cache.set(cache_key, result, timeout=43200)
    return result
