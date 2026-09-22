from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from users.utils import build_absolute_media_url
from social.models import Story, StoryView, StoryLike
from .outfit_serializers import UserSimpleSerializer


class StorySerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single story item.
    """
    user = UserSimpleSerializer(read_only=True)
    image = AbsoluteImageField(max_length=500, required=False)
    caption = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    media = serializers.SerializerMethodField(read_only=True)
    media_type = serializers.SerializerMethodField(read_only=True)
    views_count = serializers.ReadOnlyField()
    loves_count = serializers.ReadOnlyField()
    has_viewed = serializers.SerializerMethodField()
    has_loved = serializers.SerializerMethodField()
    time_remaining_seconds = serializers.SerializerMethodField()
    recent_viewers = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            'id',
            'user',
            'image',
            'media',
            'media_type',
            'caption',
            'created_at',
            'expires_at',
            'time_remaining_seconds',
            'views_count',
            'loves_count',
            'has_viewed',
            'has_loved',
            'recent_viewers',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'expires_at', 'views_count', 'loves_count', 'media', 'media_type']

    def to_internal_value(self, data):
        if hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        # Map media / file aliases to image
        for alias in ('media', 'file', 'media_file', 'picture', 'story_image'):
            if alias in data and 'image' not in data:
                data['image'] = data[alias]
                break

        request = self.context.get('request')
        if request and hasattr(request, 'FILES') and request.FILES:
            for alias in ('media', 'file', 'media_file', 'picture', 'story_image'):
                if alias in request.FILES and 'image' not in request.FILES:
                    data['image'] = request.FILES[alias]
                    break

        return super().to_internal_value(data)

    def validate(self, attrs):
        request = self.context.get('request')
        if not attrs.get('image') and request and hasattr(request, 'FILES') and request.FILES:
            for alias in ('image', 'media', 'file', 'media_file', 'picture', 'story_image'):
                if alias in request.FILES:
                    attrs['image'] = request.FILES[alias]
                    break

        if not attrs.get('image') and self.instance is None:
            raise serializers.ValidationError({
                'image': "Story picture or media file is required. Please upload an image file under 'media' or 'image'."
            })

        if attrs.get('image'):
            validate_image_file(attrs['image'], max_mb=30)

        return attrs

    def get_media(self, obj):
        if obj.image:
            return build_absolute_media_url(obj.image, request=self.context.get('request'))
        return None

    def get_media_type(self, obj):
        return 'image'

    def validate_image(self, value):
        if value:
            return validate_image_file(value, max_mb=30)
        return value

    def get_time_remaining_seconds(self, obj):
        if not obj.expires_at:
            return 0
        rem = (obj.expires_at - timezone.now()).total_seconds()
        return max(0, int(rem))

    @extend_schema_field(serializers.BooleanField)
    def get_has_viewed(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        viewed_story_ids = self.context.get('viewed_story_ids')
        if viewed_story_ids is not None:
            return obj.id in viewed_story_ids
        return StoryView.objects.filter(story=obj, viewer=request.user).exists()

    @extend_schema_field(serializers.BooleanField)
    def get_has_loved(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if obj.user_id == request.user.id:
            return False
        loved_story_ids = self.context.get('loved_story_ids')
        if loved_story_ids is not None:
            return obj.id in loved_story_ids
        return StoryLike.objects.filter(story=obj, user=request.user).exists()

    def get_recent_viewers(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or obj.user_id != request.user.id:
            return None
        if 'views' in getattr(obj, '_prefetched_objects_cache', {}):
            recent_views = [v for v in obj.views.all() if v.viewer_id != obj.user_id][:5]
        else:
            recent_views = list(obj.views.exclude(viewer=obj.user).select_related('viewer')[:5])

        if 'likes' in getattr(obj, '_prefetched_objects_cache', {}):
            loved_user_ids = {l.user_id for l in obj.likes.all() if l.user_id != obj.user_id}
        else:
            loved_user_ids = set(obj.likes.exclude(user=obj.user).values_list('user_id', flat=True))

        return [
            {
                'viewer': UserSimpleSerializer(v.viewer, context=self.context).data,
                'viewed_at': v.viewed_at,
                'has_loved': v.viewer_id in loved_user_ids,
            }
            for v in recent_views
        ]


class UserStoryGroupSerializer(serializers.Serializer):
    """
    Groups active stories by user for the horizontal story bar (inbox / social feed).
    """
    user = UserSimpleSerializer()
    has_unseen_story = serializers.BooleanField()
    total_stories = serializers.IntegerField()
    stories = StorySerializer(many=True)


class StoryViewerSerializer(serializers.ModelSerializer):
    """
    Serializer for story owner viewing who viewed their story and if they gave love/heart.
    """
    viewer = UserSimpleSerializer(read_only=True)
    has_loved = serializers.SerializerMethodField()

    class Meta:
        model = StoryView
        fields = ['viewer', 'viewed_at', 'has_loved']

    @extend_schema_field(serializers.BooleanField)
    def get_has_loved(self, obj):
        loved_user_ids = self.context.get('loved_user_ids')
        if loved_user_ids is not None:
            return obj.viewer_id in loved_user_ids
        return StoryLike.objects.filter(story=obj.story, user=obj.viewer).exists()
