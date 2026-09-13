from rest_framework import serializers

from users.fields import AbsoluteImageField
from users.utils import build_absolute_media_url
from social.models import DirectMessage
from .outfit_serializers import UserSimpleSerializer


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
