from rest_framework import serializers
from users.fields import AbsoluteImageField
from closet.models import FitCheck, LLMCostLog
from .item_serializers import ClosetItemSerializer


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
