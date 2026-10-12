from rest_framework import serializers
from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from closet.models import ClosetItem


class ClosetItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ClosetItem read, create, and update.
    """
    image = AbsoluteImageField(max_length=500, required=False, allow_null=True)
    per_wear_cost = serializers.ReadOnlyField()

    class Meta:
        model = ClosetItem
        fields = [
            'id',
            'fit_check',
            'name',
            'category',
            'color',
            'brand',
            'size',
            'price',
            'currency',
            'style_vibe',
            'pattern',
            'style_tags',
            'occasion',
            'fit',
            'attr_sentence_en',
            'confidence',
            'source',
            'photo_sha256',
            'image',
            'times_worn',
            'per_wear_cost',
            'last_worn_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'times_worn',
            'per_wear_cost',
            'last_worn_at',
            'created_at',
            'updated_at',
            'photo_sha256',
        ]

    def validate_image(self, value):
        """Validate cloth image format and max 10MB size (P-12)"""
        if value:
            return validate_image_file(value, max_mb=10)
        return value

    def validate_price(self, value):
        """Ensure cloth price cannot be negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value
