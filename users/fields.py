"""
Custom DRF serializer fields for media and image handling.
"""

from rest_framework import serializers
from .utils import build_absolute_media_url


class AbsoluteImageField(serializers.ImageField):
    """
    ImageField that:
    1. Validates and processes multipart file uploads on write (create/update).
    2. Serializes to a complete, absolute HTTPS URL on read (to_representation).
    """

    def to_representation(self, value):
        if not value:
            return None
        request = self.context.get('request', None) if getattr(self, 'context', None) else None
        return build_absolute_media_url(value, request=request)
