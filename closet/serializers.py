from rest_framework import serializers
from users.validators import validate_image_file
from .models import ClosetItem

class ClosetItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ClosetItem read, create, and update
    """
    image = serializers.ImageField(max_length=500, required=False, allow_null=True)
    per_wear_cost = serializers.ReadOnlyField()

    class Meta:
        model = ClosetItem
        fields = [
            'id',
            'name',
            'category',
            'color',
            'brand',
            'size',
            'price',
            'image',
            'times_worn',
            'per_wear_cost',
            'last_worn_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'times_worn', 'per_wear_cost', 'last_worn_at', 'created_at', 'updated_at']

    def validate_image(self, value):
        """Validate cloth image format and max 30MB size"""
        if value:
            return validate_image_file(value, max_mb=30)
        return value

    def validate_price(self, value):
        """Ensure cloth price cannot be negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

