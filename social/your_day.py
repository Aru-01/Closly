"""
Backward-compatibility facade for Your Day Weather & Smart Wardrobe Recommender Engine.
Logic has been modularized into social.services.your_day_services.
"""
from social.services.your_day_services import (
    get_live_weather,
    suggest_daily_outfit,
    WMO_WEATHER_CODES,
    DACH_CITY_CENTROIDS,
)

__all__ = [
    'get_live_weather',
    'suggest_daily_outfit',
    'WMO_WEATHER_CODES',
    'DACH_CITY_CENTROIDS',
]
