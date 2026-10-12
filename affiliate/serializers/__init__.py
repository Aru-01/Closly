"""
Affiliate serializers package.
Re-exports all serializers to maintain 100% backward compatibility.
"""

from .feed_serializers import (
    fix_image_url,
    BrandSerializer,
    AffiliateProductListSerializer,
    AffiliateProductDetailSerializer,
)

from .telemetry_serializers import (
    EventItemSerializer,
    EventBatchSerializer,
)

from .conversion_serializers import (
    ConversionSerializer,
)

__all__ = [
    'fix_image_url',
    'BrandSerializer',
    'AffiliateProductListSerializer',
    'AffiliateProductDetailSerializer',
    'EventItemSerializer',
    'EventBatchSerializer',
    'ConversionSerializer',
]
