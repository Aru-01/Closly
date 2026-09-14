from rest_framework import serializers
from django.contrib.auth import get_user_model
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
        fields = ['id', 'email', 'name', 'profile_picture']

    def get_profile_picture(self, obj):
        if obj.profile_picture:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None


class TodayOutfitSerializer(serializers.ModelSerializer):
    """
    Serializer for TodayOutfit creation and feed listing
    """
    user = UserSimpleSerializer(read_only=True)
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
    Serializer for follow/unfollow relationships
    """
    follower = UserSimpleSerializer(read_only=True)
    following = UserSimpleSerializer(read_only=True)

    class Meta:
        model = UserFollow
        fields = ['id', 'follower', 'following', 'created_at']


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
