import json
import logging
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field

from users.validators import validate_image_file
from users.fields import AbsoluteImageField
from users.utils import build_absolute_media_url
from social.models import TodayOutfit, OutfitImage, OutfitLike
from closet.models import ClosetItem
from closet.serializers import ClosetItemSerializer

logger = logging.getLogger(__name__)
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
    likes_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()
    tagged_items = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ClosetItem.objects.none(),
        required=False
    )
    tagged_items_details = ClosetItemSerializer(source='tagged_items', many=True, read_only=True)
    style_category = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    weather_tag = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
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
            images_list = get_file_list('images')
            if images_list:
                uploaded_files = images_list
            else:
                image_list = get_file_list('image')
                if image_list:
                    uploaded_files = image_list
                else:
                    for key in sorted(request.FILES.keys()):
                        if key.startswith('image'):
                            uploaded_files.extend(get_file_list(key))

        if not uploaded_files and attrs.get('image'):
            uploaded_files = [attrs['image']]

        count = len(uploaded_files)

        if count > 4:
            raise serializers.ValidationError({
                'images': f"Maximum 4 images are allowed per outfit post. You provided {count} images."
            })

        if self.instance is None and count == 0:
            raise serializers.ValidationError({
                'images': "Outfit image is required. Please upload at least 1 image (maximum 4 allowed)."
            })

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
            item_ids = [it.id if hasattr(it, 'id') else it for it in tagged_items]
            ClosetItem.objects.filter(id__in=item_ids).update(
                times_worn=F('times_worn') + 1,
                last_worn_at=timezone.now()
            )
            if hasattr(outfit, '_prefetched_objects_cache'):
                outfit._prefetched_objects_cache.pop('tagged_items', None)

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
        if hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        for alias in ('clothes', 'cloth_ids', 'clothes_ids', 'clothes_items', 'items', 'cloth_id'):
            if alias in data and 'tagged_items' not in data:
                data['tagged_items'] = data[alias]
                break

        if 'warm_tag' in data and 'weather_tag' not in data:
            data['weather_tag'] = data['warm_tag']

        if 'visibility' in data:
            v_val = str(data['visibility']).strip().lower().replace('"', '').replace("'", "")
            data['visibility'] = v_val

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
                        try:
                            _extract_ids(json.loads(s))
                            return
                        except Exception as e:
                            logger.warning(f"Error parsing tagged items json: {e}")
                    for part in s.split(','):
                        part = part.strip()
                        if part.isdigit():
                            clean_ids.append(int(part))
                elif isinstance(val, (int, float)):
                    clean_ids.append(int(val))

            _extract_ids(items_val)

            if hasattr(data, 'setlist'):
                data.setlist('tagged_items', clean_ids)
            else:
                data['tagged_items'] = clean_ids

        return super().to_internal_value(data)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_images(self, obj):
        request = self.context.get('request')
        images = list(obj.images.all())
        if images:
            return [build_absolute_media_url(img.image, request=request) for img in images]
        elif obj.image:
            return [build_absolute_media_url(obj.image, request=request)]
        return []

    @extend_schema_field(OutfitImageSerializer(many=True))
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
                for img in images
            ] if False else [
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
