from rest_framework import serializers
from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from .models import ClosetItem, FitCheck, LLMCostLog


class ClosetItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ClosetItem read, create, and update
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
        """Validate cloth image format and max 30MB size"""
        if value:
            return validate_image_file(value, max_mb=30)
        return value

    def validate_price(self, value):
        """Ensure cloth price cannot be negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value


class FitCheckSerializer(serializers.ModelSerializer):
    photo = AbsoluteImageField(max_length=500, required=False, allow_null=True)
    items = ClosetItemSerializer(many=True, source='closet_items', read_only=True)

    class Meta:
        model = FitCheck
        fields = [
            'id',
            'status',
            'photo',
            'photo_sha256',
            'nsfw_score',
            'tagging_model',
            'provider',
            'cost_cents',
            'error_code',
            'items',
            'created_at',
            'tagged_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'photo',
            'photo_sha256',
            'nsfw_score',
            'tagging_model',
            'provider',
            'cost_cents',
            'error_code',
            'items',
            'created_at',
            'tagged_at',
        ]


class LLMCostLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMCostLog
        fields = [
            'id',
            'fit_check',
            'task',
            'provider',
            'model',
            'input_tokens',
            'output_tokens',
            'cost_cents',
            'latency_ms',
            'success',
            'error_code',
            'created_at',
        ]
        read_only_fields = fields
