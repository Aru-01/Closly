from rest_framework import serializers
from social.models import ContentReport, TodayOutfit, Story
from django.contrib.auth import get_user_model

User = get_user_model()


class ContentReportSerializer(serializers.ModelSerializer):
    """
    Serializer for creating DSA/App Store user content reports.
    """
    class Meta:
        model = ContentReport
        fields = [
            'id',
            'target_type',
            'target_id',
            'reason',
            'details',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

    def validate(self, attrs):
        target_type = attrs.get('target_type')
        target_id = str(attrs.get('target_id', '')).strip()

        if not target_id:
            raise serializers.ValidationError({'target_id': 'Target ID is required.'})

        if target_type == 'outfit':
            try:
                pk = int(target_id)
                if not TodayOutfit.objects.filter(pk=pk).exists():
                    raise serializers.ValidationError({'target_id': 'Referenced outfit does not exist.'})
            except (ValueError, TypeError):
                raise serializers.ValidationError({'target_id': 'Invalid outfit ID.'})
        elif target_type == 'story':
            try:
                pk = int(target_id)
                if not Story.objects.filter(pk=pk).exists():
                    raise serializers.ValidationError({'target_id': 'Referenced story does not exist.'})
            except (ValueError, TypeError):
                raise serializers.ValidationError({'target_id': 'Invalid story ID.'})
        elif target_type == 'user':
            if not User.objects.filter(pk=target_id).exists():
                raise serializers.ValidationError({'target_id': 'Referenced user does not exist.'})

        return attrs
