"""
AI Closet Scanner package. Re-exports all scanner functions to maintain 100% backward compatibility.
"""

from .colors import (
    FASHION_COLOR_PALETTES,
    _color_distance,
    detect_dominant_fashion_color,
    sample_image_zone_color,
)

from .geometry import (
    classify_garment_geometry,
    analyze_multi_item_outfit,
)

from .gemini_client import (
    call_gemini_vision_api,
)

from .scanner import (
    scan_clothing_image,
)

__all__ = [
    'FASHION_COLOR_PALETTES',
    '_color_distance',
    'detect_dominant_fashion_color',
    'sample_image_zone_color',
    'classify_garment_geometry',
    'analyze_multi_item_outfit',
    'call_gemini_vision_api',
    'scan_clothing_image',
]
