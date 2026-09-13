from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers

from social.models import UserFollow
from .outfit_serializers import UserSimpleSerializer


class UserFollowSerializer(serializers.ModelSerializer):
    """
    Serializer for follow/unfollow relationships with DNA match, 14-day recency, and location synergy
    """
    follower = UserSimpleSerializer(read_only=True)
    following = UserSimpleSerializer(read_only=True)
    dna_match = serializers.SerializerMethodField()
    is_new = serializers.SerializerMethodField()
    same_location = serializers.SerializerMethodField()

    class Meta:
        model = UserFollow
        fields = ['id', 'follower', 'following', 'dna_match', 'is_new', 'same_location', 'created_at']

    def get_target_user(self, obj):
        request = self.context.get('request')
        view_type = self.context.get('view_type')
        if view_type == 'following':
            return obj.following
        elif view_type == 'followers':
            return obj.follower
        if request and request.user.is_authenticated and obj.follower_id == request.user.id:
            return obj.following
        return obj.follower

    def get_dna_match(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        partner = self.get_target_user(obj)
        from social.dna import calculate_dna_match
        return calculate_dna_match(request.user, partner)

    def get_is_new(self, obj):
        return obj.created_at >= timezone.now() - timedelta(days=14)

    def get_same_location(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        partner = self.get_target_user(obj)
        u = request.user
        if u.city and partner.city and u.city.strip().lower() == partner.city.strip().lower():
            return True
        if u.country and partner.country and u.country.strip().lower() == partner.country.strip().lower():
            return True
        return False
