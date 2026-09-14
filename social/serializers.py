from rest_framework import serializers
from django.contrib.auth import get_user_model
from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from users.utils import build_absolute_media_url
from .models import TodayOutfit, OutfitLike, UserFollow, DirectMessage
from closet.serializers import ClosetItemSerializer

User = get_user_model()

class UserSimpleSerializer(serializers.ModelSerializer):
    """
    Simplified user serializer for author details in feed & social features
    """
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'country', 'city', 'profile_picture']

    def get_profile_picture(self, obj):
        if obj.profile_picture:
            return build_absolute_media_url(obj.profile_picture, request=self.context.get('request'))
        return None


class TodayOutfitSerializer(serializers.ModelSerializer):
    """
    Serializer for TodayOutfit creation and feed listing
    """
    user = UserSimpleSerializer(read_only=True)
    image = AbsoluteImageField(max_length=500, required=True)
    likes_count = serializers.ReadOnlyField()
    is_liked = serializers.SerializerMethodField()
    tagged_items_details = ClosetItemSerializer(source='tagged_items', many=True, read_only=True)

    class Meta:
        model = TodayOutfit
        fields = [
            'id',
            'user',
            'image',
            'caption',
            'visibility',
            'tagged_items',
            'tagged_items_details',
            'likes_count',
            'is_liked',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'likes_count', 'is_liked', 'created_at', 'updated_at']

    def validate_image(self, value):
        """Validate outfit image format and max 30MB size"""
        if value:
            return validate_image_file(value, max_mb=30)
        return value

    def get_is_liked(self, obj):
        liked_outfit_ids = self.context.get('liked_outfit_ids')
        if liked_outfit_ids is not None:
            return obj.id in liked_outfit_ids

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return OutfitLike.objects.filter(outfit=obj, user=request.user).exists()
        return False


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
        from .dna import calculate_dna_match
        return calculate_dna_match(request.user, partner)

    def get_is_new(self, obj):
        from django.utils import timezone
        from datetime import timedelta
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


class DirectMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for direct messages
    """
    sender = UserSimpleSerializer(read_only=True)
    recipient = UserSimpleSerializer(read_only=True)

    class Meta:
        model = DirectMessage
        fields = ['id', 'sender', 'recipient', 'content', 'is_read', 'created_at']
        read_only_fields = ['id', 'sender', 'recipient', 'is_read', 'created_at']


class ConversationLastMessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    content = serializers.CharField()
    sender_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    is_read = serializers.BooleanField()


class ConversationSummarySerializer(serializers.Serializer):
    other_user = UserSimpleSerializer()
    last_message = ConversationLastMessageSerializer()
    unread_count = serializers.IntegerField()


