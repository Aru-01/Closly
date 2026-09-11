from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Notification

User = get_user_model()


class NotificationSenderSerializer(serializers.ModelSerializer):
    """Simplified user serializer for notification sender preview"""
    profile_picture = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()
    last_seen = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'profile_picture', 'is_online', 'last_seen']

    def get_profile_picture(self, obj):
        if obj.profile_picture:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None

    def get_is_online(self, obj):
        from users.utils import is_user_online
        return is_user_online(obj.id)

    def get_last_seen(self, obj):
        from users.utils import get_user_last_seen
        return get_user_last_seen(obj)


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for in-app notifications
    """
    sender = NotificationSenderSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'sender',
            'notification_type',
            'title',
            'message',
            'data',
            'is_read',
            'created_at',
        ]
        read_only_fields = ['id', 'sender', 'created_at']
