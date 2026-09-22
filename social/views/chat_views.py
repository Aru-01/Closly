import logging
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q, Count

from social.models import TodayOutfit, DirectMessage, Story
from affiliate.models import AffiliateProduct
from social.serializers import (
    DirectMessageSerializer,
    ConversationSummarySerializer,
)
from drf_spectacular.utils import extend_schema, OpenApiResponse

logger = logging.getLogger(__name__)
User = get_user_model()
from users.validators import validate_image_file
from users.utils import compress_chat_image
from .outfit_views import StandardSocialPagination
from .story_views import get_active_stories_for_user

@extend_schema(
    tags=["Direct Messaging & Chat"],
    summary="Send Direct Message",
    description="Send a 1-on-1 direct message with optional text, image attachment, shared product, shared outfit, or story reply.",
    responses={
        201: DirectMessageSerializer,
        400: OpenApiResponse(description="Validation error or self-messaging"),
        404: OpenApiResponse(description="Target recipient or shared reference not found"),
    }
)
class DirectMessageSendView(APIView):
    """
    API endpoint to send a direct message to a user.
    Supports text, image attachments, shared products, shared outfits, and story replies.
    
    POST /api/social/messages/
    Body (multipart/form-data or JSON):
    - recipient_id: UUID (required)
    - message_type: 'text' | 'image' | 'product' | 'outfit' | 'story_reply' (optional)
    - content: string (optional if attachment/shared item is provided)
    - image: file (optional, image attachment)
    - product_id: int (optional, shared AffiliateProduct)
    - outfit_id: int (optional, shared TodayOutfit)
    - story_id: int (optional, replied Story)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        recipient_id = request.data.get('recipient_id')
        message_type = request.data.get('message_type', 'text')
        content = request.data.get('content', '')
        image_file = request.FILES.get('image')
        product_id = request.data.get('product_id')
        outfit_id = request.data.get('outfit_id')
        story_id = request.data.get('story_id')

        if not recipient_id:
            return Response({
                'success': False,
                'message': 'recipient_id is required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if str(recipient_id) == str(request.user.id):
            return Response({
                'success': False,
                'message': 'You cannot send a direct message to yourself.'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            recipient = get_object_or_404(User, pk=recipient_id)
        except (ValidationError, ValueError):
            return Response({
                'success': False,
                'message': 'Invalid user ID format.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not recipient.is_active:
            return Response({
                'success': False,
                'message': 'This user is no longer on Closly.'
            }, status=status.HTTP_400_BAD_REQUEST)

        shared_product = None
        if product_id:
            try:
                shared_product = AffiliateProduct.objects.filter(pk=product_id).first()
            except (ValueError, TypeError, ValidationError):
                shared_product = None
            if not shared_product:
                return Response({'success': False, 'message': 'Shared product not found.'}, status=status.HTTP_404_NOT_FOUND)
            message_type = 'product'

        shared_outfit = None
        if outfit_id:
            try:
                shared_outfit = TodayOutfit.objects.filter(pk=outfit_id).first()
            except (ValueError, TypeError, ValidationError):
                shared_outfit = None
            if not shared_outfit:
                return Response({'success': False, 'message': 'Shared outfit not found.'}, status=status.HTTP_404_NOT_FOUND)
            message_type = 'outfit'

        story_ref = None
        if story_id:
            try:
                story_ref = Story.objects.filter(pk=story_id).first()
            except (ValueError, TypeError, ValidationError):
                story_ref = None
            if not story_ref:
                return Response({'success': False, 'message': 'Referenced story not found.'}, status=status.HTTP_404_NOT_FOUND)
            message_type = 'story_reply'

        if image_file:
            try:
                validate_image_file(image_file, max_mb=30)
                image_file = compress_chat_image(image_file)
            except ValidationError as e:
                return Response({
                    'success': False,
                    'message': 'Invalid image attachment.',
                    'errors': {'image': list(e.messages) if hasattr(e, 'messages') else [str(e)]}
                }, status=status.HTTP_400_BAD_REQUEST)
            message_type = 'image'

        if not content and not image_file and not shared_product and not shared_outfit and not story_ref:
            return Response({
                'success': False,
                'message': 'Message must contain text content, an image, or a shared item.'
            }, status=status.HTTP_400_BAD_REQUEST)

        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            message_type=message_type,
            content=content or '',
            image=image_file,
            shared_product=shared_product,
            shared_outfit=shared_outfit,
            story_reference=story_ref,
        )

        if recipient != request.user:
            try:
                from notifications.services import create_notification
                if message_type == 'outfit':
                    notif_type = 'outfit_shared'
                    notif_title = 'Outfit Shared'
                    notif_msg = f"{request.user.name or 'Someone'} shared an outfit with you!"
                elif message_type == 'image':
                    notif_type = 'direct_message'
                    notif_title = 'New Photo Message'
                    notif_msg = f"{request.user.name or 'Someone'} sent you a photo."
                else:
                    notif_type = 'direct_message'
                    notif_title = 'New Message'
                    preview_text = content[:60] if content else f"Sent you a {message_type}"
                    notif_msg = f"{request.user.name or 'A user'}: {preview_text}"

                create_notification(
                    recipient=recipient,
                    sender=request.user,
                    notification_type=notif_type,
                    title=notif_title,
                    message=notif_msg,
                    data={'sender_id': str(request.user.id), 'deep_link': f"closly://chat/{request.user.id}"}
                )
            except Exception:
                pass

        serializer = DirectMessageSerializer(message, context={'request': request})

        # Broadcast in real time to recipient's WebSocket channel group
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f"user_{recipient.id}",
                    {
                        "type": "chat_message_handler",
                        "data": serializer.data
                    }
                )
        except Exception as ws_err:
            logger.warning(f"Failed to broadcast chat message via WebSocket: {ws_err}")

        return Response({
            'success': True,
            'message': 'Message sent successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Direct Messaging & Chat"],
    summary="Get Conversation Messages",
    description="Retrieve paginated message history between authenticated user and another user, marking incoming messages as read.",
    responses={
        200: DirectMessageSerializer(many=True),
    }
)
class DirectMessageConversationView(generics.ListAPIView):
    """
    API endpoint to retrieve full conversation messages between current user and a target user.
    
    GET /api/social/messages/<user_id>/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = DirectMessageSerializer
    pagination_class = StandardSocialPagination

    def get_queryset(self):
        other_user_id = self.kwargs.get('user_id')
        current_user = self.request.user
        
        # Mark received messages from this user as read
        DirectMessage.objects.filter(sender_id=other_user_id, recipient=current_user, is_read=False).update(is_read=True)

        return (
            DirectMessage.objects.filter(
                (Q(sender=current_user) & Q(recipient_id=other_user_id)) |
                (Q(sender_id=other_user_id) & Q(recipient=current_user))
            )
            .select_related('sender', 'recipient', 'shared_product', 'shared_outfit', 'shared_outfit__user', 'story_reference', 'story_reference__user')
        )


@extend_schema(
    tags=["Direct Messaging & Chat"],
    summary="List Conversations (Inbox) & Active Stories Tray",
    description="List all active 1-on-1 conversations sorted by recency with unread counters, plus followed users' active 24h stories tray.",
    responses={
        200: OpenApiResponse(description="Inbox threads and active stories bar retrieved successfully"),
    }
)
class ConversationListView(APIView):
    """
    API endpoint to list user's conversation threads (Inbox) + Active Stories Tray.
    Returns all conversations grouped by partner user, ordered by latest message time,
    along with active stories of followed users for the top story bar.

    GET /api/social/conversations/
    GET /api/social/messages/inbox/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user

        # 1. Fetch unread counts grouped by sender in 1 query
        unread_counts_qs = (
            DirectMessage.objects.filter(recipient=user, is_read=False)
            .values('sender_id')
            .annotate(count=Count('id'))
        )
        unread_map = {item['sender_id']: item['count'] for item in unread_counts_qs}

        # 2. Fetch all messages involving user, ordered newest first with related users
        messages = (
            DirectMessage.objects.filter(Q(sender=user) | Q(recipient=user))
            .select_related('sender', 'recipient')
            .order_by('-created_at', '-id')
        )

        # 3. Deduplicate by conversation partner while preserving latest message
        conversations = {}
        for msg in messages:
            partner = msg.recipient if msg.sender_id == user.id else msg.sender
            if partner.id not in conversations:
                conversations[partner.id] = {
                    'other_user': partner,
                    'last_message': {
                        'id': msg.id,
                        'message_type': msg.message_type,
                        'content': msg.content,
                        'sender_id': str(msg.sender_id),
                        'created_at': msg.created_at,
                        'is_read': msg.is_read,
                    },
                    'unread_count': unread_map.get(partner.id, 0),
                }

        serializer = ConversationSummarySerializer(
            list(conversations.values()),
            many=True,
            context={'request': request}
        )

        # Fetch active stories for the top horizontal story bar
        stories_data = get_active_stories_for_user(user, request=request)

        return Response({
            'success': True,
            'message': 'Conversations and stories retrieved successfully.',
            'data': serializer.data,
            'stories': stories_data,
        }, status=status.HTTP_200_OK)


