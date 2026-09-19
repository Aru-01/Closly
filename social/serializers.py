from rest_framework import serializers
from django.contrib.auth import get_user_model
from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from users.utils import build_absolute_media_url
from .models import (
    TodayOutfit,
    OutfitImage,
    OutfitLike,
    UserFollow,
    DirectMessage,
    Story,
    StoryView,
    StoryLike,
)
from closet.serializers import ClosetItemSerializer
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field


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


class OutfitImageSerializer(serializers.ModelSerializer):
    """
    Serializer for individual outfit gallery images
    """
    image = serializers.SerializerMethodField()

    class Meta:
        model = OutfitImage
        fields = ['id', 'image', 'order']

    def get_image(self, obj):
        if obj.image:
            return build_absolute_media_url(obj.image, request=self.context.get('request'))
        return None


class TodayOutfitSerializer(serializers.ModelSerializer):
    """
    Serializer for TodayOutfit creation, feed listing, and updates.
    Supports 1 to 4 images per outfit post with max 4 image validation.
    """
    user = UserSimpleSerializer(read_only=True)
    image = AbsoluteImageField(max_length=500, required=False)
    images = serializers.SerializerMethodField()
    images_details = serializers.SerializerMethodField()
    likes_count = serializers.ReadOnlyField()
    is_liked = serializers.SerializerMethodField()
    tagged_items_details = ClosetItemSerializer(source='tagged_items', many=True, read_only=True)
    style_category = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    weather_tag = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')

    class Meta:
        model = TodayOutfit
        fields = [
            'id',
            'user',
            'image',
            'images',
            'images_details',
            'caption',
            'visibility',
            'style_category',
            'weather_tag',
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

    def validate(self, attrs):
        request = self.context.get('request')
        uploaded_files = []

        if request and hasattr(request, 'FILES') and request.FILES:
            # 1. Check if multiple files are passed under 'images'
            images_list = request.FILES.getlist('images')
            if images_list:
                uploaded_files = images_list
            else:
                # 2. Check if multiple files are passed under 'image'
                image_list = request.FILES.getlist('image')
                if image_list:
                    uploaded_files = image_list
                else:
                    # 3. Check numbered keys like image_1, image_2, etc.
                    for key in sorted(request.FILES.keys()):
                        if key.startswith('image'):
                            uploaded_files.extend(request.FILES.getlist(key))

        # Check for direct attribute (e.g. from unit tests passing 'image' file directly)
        if not uploaded_files and attrs.get('image'):
            uploaded_files = [attrs['image']]

        count = len(uploaded_files)

        # Strict validation: Maximum 4 images per outfit post
        if count > 4:
            raise serializers.ValidationError({
                'images': f"Maximum 4 images are allowed per outfit. You provided {count} images."
            })

        # Mandatory image check on creation
        if self.instance is None and count == 0:
            raise serializers.ValidationError({
                'images': "Outfit image is required. Please upload at least 1 image (maximum 4 allowed)."
            })

        # Validate each uploaded file (file format & max 30MB size)
        for f in uploaded_files:
            validate_image_file(f, max_mb=30)

        if uploaded_files:
            attrs['image'] = uploaded_files[0]
            attrs['_uploaded_images'] = uploaded_files

        return attrs

    def create(self, validated_data):
        uploaded_images = validated_data.pop('_uploaded_images', [])
        tagged_items = validated_data.pop('tagged_items', None)
        outfit = TodayOutfit.objects.create(**validated_data)
        if tagged_items:
            outfit.tagged_items.set(tagged_items)

        # Store all uploaded images (orders 0, 1, 2, 3) in OutfitImage
        if uploaded_images:
            OutfitImage.objects.bulk_create([
                OutfitImage(outfit=outfit, image=img_file, order=idx)
                for idx, img_file in enumerate(uploaded_images)
            ])
        elif outfit.image:
            OutfitImage.objects.create(outfit=outfit, image=outfit.image, order=0)

        return outfit

    def update(self, instance, validated_data):
        uploaded_images = validated_data.pop('_uploaded_images', None)
        tagged_items = validated_data.pop('tagged_items', None)

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if tagged_items is not None:
            instance.tagged_items.set(tagged_items)

        # If new images were provided in update, replace existing images
        if uploaded_images:
            instance.images.all().delete()
            OutfitImage.objects.bulk_create([
                OutfitImage(outfit=instance, image=img_file, order=idx)
                for idx, img_file in enumerate(uploaded_images)
            ])
            instance.image = uploaded_images[0]
            instance.save(update_fields=['image'])

        return instance

    def to_internal_value(self, data):
        # Handle QueryDict / multipart dict copying
        if hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        # Support alias clothes_items -> tagged_items
        if 'clothes_items' in data and 'tagged_items' not in data:
            data['tagged_items'] = data['clothes_items']

        # Support alias warm_tag -> weather_tag
        if 'warm_tag' in data and 'weather_tag' not in data:
            data['weather_tag'] = data['warm_tag']

        # Support is_public boolean alias for visibility ('public'|'private')
        if 'is_public' in data and 'visibility' not in data:
            val = data['is_public']
            if isinstance(val, str):
                val = val.lower() in ('true', '1', 'yes')
            data['visibility'] = 'public' if val else 'private'

        # Support stringified JSON or comma-separated tagged_items in multipart form-data
        if 'tagged_items' in data:
            items_val = data['tagged_items']
            if isinstance(items_val, str):
                items_val = items_val.strip()
                if items_val.startswith('[') and items_val.endswith(']'):
                    import json
                    try:
                        data['tagged_items'] = json.loads(items_val)
                    except Exception:
                        pass
                elif ',' in items_val:
                    data['tagged_items'] = [int(x.strip()) for x in items_val.split(',') if x.strip().isdigit()]
                elif items_val.isdigit():
                    data['tagged_items'] = [int(items_val)]

        return super().to_internal_value(data)

    def get_images(self, obj):
        request = self.context.get('request')
        images = list(obj.images.all())
        if images:
            return [build_absolute_media_url(img.image, request=request) for img in images]
        elif obj.image:
            return [build_absolute_media_url(obj.image, request=request)]
        return []

    def get_images_details(self, obj):
        request = self.context.get('request')
        images = list(obj.images.all())
        if images:
            return [
                {
                    'id': img.id,
                    'image': build_absolute_media_url(img.image, request=request),
                    'order': img.order,
                }
                for img in images
            ]
        elif obj.image:
            return [
                {
                    'id': None,
                    'image': build_absolute_media_url(obj.image, request=request),
                    'order': 0,
                }
            ]
        return []

    @extend_schema_field(serializers.BooleanField)
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

class StorySerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single story item.
    """
    user = UserSimpleSerializer(read_only=True)
    image = AbsoluteImageField(max_length=500, required=True)
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
        read_only_fields = ['id', 'user', 'created_at', 'expires_at', 'views_count', 'loves_count']

    def validate_image(self, value):
        if value:
            return validate_image_file(value, max_mb=30)
        return value

    def get_time_remaining_seconds(self, obj):
        if not obj.expires_at:
            return 0
        rem = (obj.expires_at - timezone.now()).total_seconds()
        return max(0, int(rem))

    def get_has_viewed(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        viewed_story_ids = self.context.get('viewed_story_ids')
        if viewed_story_ids is not None:
            return obj.id in viewed_story_ids
        return StoryView.objects.filter(story=obj, viewer=request.user).exists()

    def get_has_loved(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        loved_story_ids = self.context.get('loved_story_ids')
        if loved_story_ids is not None:
            return obj.id in loved_story_ids
        return StoryLike.objects.filter(story=obj, user=request.user).exists()

    def get_recent_viewers(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or obj.user_id != request.user.id:
            return None
        recent_views = obj.views.select_related('viewer')[:5]
        loved_user_ids = set(obj.likes.values_list('user_id', flat=True))
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


class DirectMessageSerializer(serializers.ModelSerializer):
    """
    Enhanced serializer for direct messages supporting text, images,
    shared products, shared outfits, and story replies with rich preview cards.
    """
    sender = UserSimpleSerializer(read_only=True)
    recipient = UserSimpleSerializer(read_only=True)
    image = AbsoluteImageField(max_length=500, required=False, allow_null=True)
    product_preview = serializers.SerializerMethodField()
    outfit_preview = serializers.SerializerMethodField()
    story_preview = serializers.SerializerMethodField()

    class Meta:
        model = DirectMessage
        fields = [
            'id',
            'sender',
            'recipient',
            'message_type',
            'content',
            'image',
            'shared_product',
            'product_preview',
            'shared_outfit',
            'outfit_preview',
            'story_reference',
            'story_preview',
            'is_read',
            'created_at',
        ]
        read_only_fields = ['id', 'sender', 'recipient', 'is_read', 'created_at']

    def get_product_preview(self, obj):
        prod = obj.shared_product
        if not prod:
            return None
        return {
            'id': prod.id,
            'name': prod.name,
            'brand': prod.brand,
            'price': str(prod.price),
            'currency': prod.currency,
            'image_url': prod.image_url,
            'aw_deep_link': prod.aw_deep_link,
            'is_active': prod.is_active,
        }

    def get_outfit_preview(self, obj):
        outfit = obj.shared_outfit
        if not outfit:
            return None
        request = self.context.get('request')
        img_url = build_absolute_media_url(outfit.image, request=request) if outfit.image else None
        return {
            'id': outfit.id,
            'author_name': outfit.user.name or outfit.user.email,
            'image_url': img_url,
            'caption': outfit.caption,
        }

    def get_story_preview(self, obj):
        story = obj.story_reference
        if not story:
            return None
        request = self.context.get('request')
        img_url = build_absolute_media_url(story.image, request=request) if story.image else None
        return {
            'id': story.id,
            'author_name': story.user.name or story.user.email,
            'image_url': img_url,
            'caption': story.caption,
            'is_expired': story.is_expired,
        }


class ConversationLastMessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    message_type = serializers.CharField()
    content = serializers.CharField()
    sender_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    is_read = serializers.BooleanField()


class ConversationSummarySerializer(serializers.Serializer):
    other_user = UserSimpleSerializer()
    last_message = ConversationLastMessageSerializer()
    unread_count = serializers.IntegerField()


