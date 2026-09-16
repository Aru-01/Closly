from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    Real-time WebSocket consumer for 1-to-1 direct messaging.
    Supports real-time chat messages, typing indicators, and read receipts.
    URL: ws://<host>/ws/chat/?token=<jwt_access_token>
    """

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            logger.warning("Rejecting unauthenticated WebSocket connection attempt.")
            await self.close(code=4001)
            return

        self.user_group = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.accept()

        await self.send_json({
            "type": "connection_established",
            "message": "Connected to Closly Real-Time Chat.",
            "user_id": str(self.user.id),
        })

    async def disconnect(self, close_code):
        if hasattr(self, "user_group"):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)

    async def receive_json(self, content):
        event_type = content.get("type", "chat_message")

        if event_type in ("chat_message", "send_message"):
            await self.handle_send_message(content)

        elif event_type == "typing":
            await self.handle_typing(content)

        elif event_type == "read_receipt":
            await self.handle_read_receipt(content)

        elif event_type in ("ping", "heartbeat"):
            await self.send_json({"type": "pong", "timestamp": timezone.now().isoformat()})

        else:
            await self.send_json({
                "type": "error",
                "message": f"Unknown event type '{event_type}'."
            })

    async def handle_send_message(self, content):
        recipient_id = content.get("recipient_id")
        text_content = content.get("content", "").strip()
        message_type = content.get("message_type", "text")
        product_id = content.get("product_id")
        outfit_id = content.get("outfit_id")
        story_id = content.get("story_id")

        if not recipient_id:
            await self.send_json({"type": "error", "message": "recipient_id is required."})
            return

        if str(recipient_id) == str(self.user.id):
            await self.send_json({"type": "error", "message": "Cannot send message to yourself."})
            return

        if not text_content and not product_id and not outfit_id and not story_id:
            await self.send_json({"type": "error", "message": "Message content or shared item is required."})
            return

        saved_data = await self.save_message_to_db(
            sender_id=self.user.id,
            recipient_id=recipient_id,
            content=text_content,
            message_type=message_type,
            product_id=product_id,
            outfit_id=outfit_id,
            story_id=story_id
        )

        if not saved_data:
            await self.send_json({"type": "error", "message": "Failed to save message. Invalid recipient or item."})
            return

        # Confirm to sender
        await self.send_json({
            "type": "message_sent",
            "data": saved_data
        })

        # Broadcast real-time to recipient's private group
        recipient_group = f"user_{recipient_id}"
        await self.channel_layer.group_send(
            recipient_group,
            {
                "type": "chat_message_handler",
                "data": saved_data
            }
        )

    async def handle_typing(self, content):
        recipient_id = content.get("recipient_id")
        is_typing = bool(content.get("is_typing", True))

        if recipient_id:
            recipient_group = f"user_{recipient_id}"
            await self.channel_layer.group_send(
                recipient_group,
                {
                    "type": "typing_handler",
                    "sender_id": str(self.user.id),
                    "sender_name": self.user.name or self.user.email,
                    "is_typing": is_typing
                }
            )

    async def handle_read_receipt(self, content):
        sender_id = content.get("sender_id")
        message_ids = content.get("message_ids", [])

        if sender_id and message_ids:
            updated_count = await self.mark_messages_as_read(sender_id=sender_id, message_ids=message_ids)
            if updated_count > 0:
                sender_group = f"user_{sender_id}"
                await self.channel_layer.group_send(
                    sender_group,
                    {
                        "type": "read_receipt_handler",
                        "reader_id": str(self.user.id),
                        "message_ids": message_ids
                    }
                )

    # ---------------- Group Handlers ---------------- #

    async def chat_message_handler(self, event):
        await self.send_json({
            "type": "new_message",
            "data": event["data"]
        })

    async def typing_handler(self, event):
        await self.send_json({
            "type": "user_typing",
            "sender_id": event["sender_id"],
            "sender_name": event["sender_name"],
            "is_typing": event["is_typing"]
        })

    async def read_receipt_handler(self, event):
        await self.send_json({
            "type": "messages_read",
            "reader_id": event["reader_id"],
            "message_ids": event["message_ids"]
        })

    # ---------------- Database Helpers ---------------- #

    @database_sync_to_async
    def save_message_to_db(self, sender_id, recipient_id, content, message_type, product_id=None, outfit_id=None, story_id=None):
        from .models import DirectMessage, TodayOutfit, Story
        from affiliate.models import AffiliateProduct
        from .serializers import DirectMessageSerializer

        try:
            recipient = User.objects.get(id=recipient_id, is_active=True)
        except (User.DoesNotExist, ValueError):
            return None

        shared_product = None
        if product_id:
            shared_product = AffiliateProduct.objects.filter(id=product_id).first()
            if shared_product:
                message_type = 'product'

        shared_outfit = None
        if outfit_id:
            shared_outfit = TodayOutfit.objects.filter(id=outfit_id).first()
            if shared_outfit:
                message_type = 'outfit'

        story_ref = None
        if story_id:
            story_ref = Story.objects.filter(id=story_id).first()
            if story_ref:
                message_type = 'story_reply'

        msg = DirectMessage.objects.create(
            sender_id=sender_id,
            recipient=recipient,
            message_type=message_type,
            content=content,
            shared_product=shared_product,
            shared_outfit=shared_outfit,
            story_reference=story_ref,
        )

        return DirectMessageSerializer(msg).data

    @database_sync_to_async
    def mark_messages_as_read(self, sender_id, message_ids):
        from .models import DirectMessage
        return DirectMessage.objects.filter(
            id__in=message_ids,
            sender_id=sender_id,
            recipient_id=self.user.id,
            is_read=False
        ).update(is_read=True)
