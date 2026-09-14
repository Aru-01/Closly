from rest_framework import serializers
from .models import UserRewardProfile, RewardPointTransaction
from .services import get_tier_info


class RewardPointTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for points transaction history
    """
    class Meta:
        model = RewardPointTransaction
        fields = [
            'id',
            'action_type',
            'points',
            'description',
            'reference_id',
            'expires_at',
            'is_expired',
            'created_at',
        ]
        read_only_fields = fields


class UserRewardProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for UserRewardProfile with detailed tier and progress metrics
    """
    tier_info = serializers.SerializerMethodField()

    class Meta:
        model = UserRewardProfile
        fields = [
            'available_points',
            'lifetime_points',
            'current_tier',
            'tier_info',
            'tier_updated_at',
        ]
        read_only_fields = fields

    def get_tier_info(self, obj):
        return get_tier_info(obj.lifetime_points, obj.available_points)
