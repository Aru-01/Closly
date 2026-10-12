from rest_framework import serializers
from users.models import Device


class DeviceSerializer(serializers.ModelSerializer):
    """
    Serializer for push notification device registration (U-29 / APNs / FCM).
    Accepts apns_token (or fcm_token / token) and platform.
    """
    token = serializers.CharField(write_only=True, required=False, allow_blank=False)
    fcm_token = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = Device
        fields = ['id', 'apns_token', 'platform', 'prefs', 'token', 'fcm_token', 'last_seen', 'created_at']
        read_only_fields = ['id', 'last_seen', 'created_at']
        extra_kwargs = {
            'apns_token': {'required': False}
        }

    def validate(self, attrs):
        # Resolve token from either apns_token, fcm_token, or token
        token_val = attrs.get('apns_token') or attrs.get('fcm_token') or attrs.get('token')
        if not token_val or not token_val.strip():
            raise serializers.ValidationError({"token": "A valid device token (apns_token, fcm_token, or token) is required."})
        attrs['apns_token'] = token_val.strip()

        # If fcm_token was supplied and platform was not explicitly set to android, default to android
        if attrs.get('fcm_token') and 'platform' not in attrs:
            attrs['platform'] = 'android'

        # Pop write-only alias keys
        attrs.pop('token', None)
        attrs.pop('fcm_token', None)
        return attrs
