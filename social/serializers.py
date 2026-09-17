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
from closet.models import ClosetItem
from closet.serializers import ClosetItemSerializer
from django.db.models import F
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
        if not getattr(obj, 'is_active', True):
            return None
        if obj.profile_picture:
            return build_absolute_media_url(obj.profile_picture, request=self.context.get('request'))
        return None

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if not getattr(instance, 'is_active', True):
            ret['name'] = 'Deleted User'
            ret['profile_picture'] = None
            ret['city'] = None
            ret['country'] = None
        return ret


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
    tagged_items = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ClosetItem.objects.none(),
        required=False
    )
    tagged_items_details = ClosetItemSerializer(source='tagged_items', many=True, read_only=True)
    # clothes = serializers.SerializerMethodField()
    # clothes_details = serializers.SerializerMethodField()
    style_category = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    weather_tag = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        # Only populate the full queryset on write operations (POST, PUT, PATCH)
        # Prevents DRF HTML form renderers on GET requests from loading all closet items
        if request and request.method in ('POST', 'PUT', 'PATCH'):
            if request.user and request.user.is_authenticated:
                self.fields['tagged_items'].queryset = ClosetItem.objects.filter(user=request.user)
            else:
                self.fields['tagged_items'].queryset = ClosetItem.objects.all()
        else:
            self.fields['tagged_items'].queryset = ClosetItem.objects.none()

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
            # 'clothes',
            # 'clothes_details',
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
            get_file_list = getattr(
                request.FILES,
                'getlist',
                lambda k: ([request.FILES[k]] if k in request.FILES else [])
            )
            # 1. Check if multiple files are passed under 'images'
            images_list = get_file_list('images')
            if images_list:
                uploaded_files = images_list
            else:
                # 2. Check if multiple files are passed under 'image'
                image_list = get_file_list('image')
                if image_list:
                    uploaded_files = image_list
                else:
                    # 3. Check numbered keys like image_1, image_2, etc.
                    for key in sorted(request.FILES.keys()):
                        if key.startswith('image'):
                            uploaded_files.extend(get_file_list(key))

        # Check for direct attribute (e.g. from unit tests passing 'image' file directly)
        if not uploaded_files and attrs.get('image'):
            uploaded_files = [attrs['image']]

        count = len(uploaded_files)

        # Strict validation: Maximum 4 images per outfit post
        if count > 4:
            raise serializers.ValidationError({
                'images': f"Maximum 4 images are allowed per outfit post. You provided {count} images."
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
            # Increment worn count for tagged clothes and update last_worn_at
            item_ids = [it.id if hasattr(it, 'id') else it for it in tagged_items]
            ClosetItem.objects.filter(id__in=item_ids).update(
                times_worn=F('times_worn') + 1,
                last_worn_at=timezone.now()
            )
            # Invalidate cached tagged_items if any so serializer output has updated times_worn
            if hasattr(outfit, '_prefetched_objects_cache'):
                outfit._prefetched_objects_cache.pop('tagged_items', None)

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
            # Increment worn count for newly added clothes
            current_ids = set(instance.tagged_items.values_list('id', flat=True))
            new_item_ids = [
                (it.id if hasattr(it, 'id') else it)
                for it in tagged_items
                if (it.id if hasattr(it, 'id') else it) not in current_ids
            ]
            if new_item_ids:
                ClosetItem.objects.filter(id__in=new_item_ids).update(
                    times_worn=F('times_worn') + 1,
                    last_worn_at=timezone.now()
                )
            instance.tagged_items.set(tagged_items)
            if hasattr(instance, '_prefetched_objects_cache'):
                instance._prefetched_objects_cache.pop('tagged_items', None)

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

        # Support aliases for clothes: clothes, cloth_ids, clothes_ids, clothes_items, items, cloth_id -> tagged_items
        for alias in ('clothes', 'cloth_ids', 'clothes_ids', 'clothes_items', 'items', 'cloth_id'):
            if alias in data and 'tagged_items' not in data:
                data['tagged_items'] = data[alias]
                break

        # Support alias warm_tag -> weather_tag
        if 'warm_tag' in data and 'weather_tag' not in data:
            data['weather_tag'] = data['warm_tag']

        # Clean up whitespace / extra quotes on visibility if provided
        if 'visibility' in data:
            v_val = str(data['visibility']).strip().lower().replace('"', '').replace("'", "")
            data['visibility'] = v_val

        # Support stringified JSON, comma-separated, single int, or list for tagged_items
        if 'tagged_items' in data:
            items_val = data['tagged_items']
            clean_ids = []

            def _extract_ids(val):
                if isinstance(val, (list, tuple)):
                    for it in val:
                        _extract_ids(it)
                elif isinstance(val, dict) and 'id' in val:
                    _extract_ids(val['id'])
                elif hasattr(val, 'id'):
                    _extract_ids(val.id)
                elif isinstance(val, str):
                    s = val.strip()
                    if s.startswith('[') and s.endswith(']'):
                        import json
                        try:
                            _extract_ids(json.loads(s))
                            return
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"Error parsing tagged items json: {e}")
                    for part in s.split(','):
                        part = part.strip()
                        if part.isdigit():
                            clean_ids.append(int(part))
                elif isinstance(val, (int, float)):
                    clean_ids.append(int(val))

            _extract_ids(items_val)

            # Important: Django QueryDict requires setlist for list values,
            # otherwise assigning a list wraps it into a nested list [[pk]]
            if hasattr(data, 'setlist'):
                data.setlist('tagged_items', clean_ids)
            else:
                data['tagged_items'] = clean_ids

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
        if hasattr(obj, '_is_liked'):
            return obj._is_liked

        liked_outfit_ids = self.context.get('liked_outfit_ids')
        if liked_outfit_ids is not None:
            obj._is_liked = obj.id in liked_outfit_ids
            return obj._is_liked

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not hasattr(request, '_liked_outfit_cache'):
                request._liked_outfit_cache = {}
            if obj.id not in request._liked_outfit_cache:
                request._liked_outfit_cache[obj.id] = OutfitLike.objects.filter(
                    outfit_id=obj.id, user_id=request.user.id
                ).exists()
            obj._is_liked = request._liked_outfit_cache[obj.id]
            return obj._is_liked
        return False

    # def get_clothes(self, obj):
    #     return []

    # def get_clothes_details(self, obj):
    #     return []

    # def to_representation(self, instance):
    #     ret = super().to_representation(instance)
    #     # Both 'clothes' and 'clothes_details' can reuse the exact same serialized list from 'tagged_items_details' if needed:
    #     # items_details = ret.get('tagged_items_details', [])
    #     # ret['clothes'] = items_details
    #     # ret['clothes_details'] = items_details
    #     return ret


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
        if 'views' in getattr(obj, '_prefetched_objects_cache', {}):
            recent_views = list(obj.views.all())[:5]
        else:
            recent_views = list(obj.views.select_related('viewer')[:5])

        if 'likes' in getattr(obj, '_prefetched_objects_cache', {}):
            loved_user_ids = {l.user_id for l in obj.likes.all()}
        else:
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


