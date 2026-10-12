import logging
from social.models import DirectMessage

logger = logging.getLogger(__name__)


def send_direct_message(sender, recipient, content: str = '', image=None, shared_product=None, shared_outfit=None, story_reply=None):
    """
    Creates and records a 1:1 direct message between users.
    """
    dm = DirectMessage.objects.create(
        sender=sender,
        recipient=recipient,
        content=content or '',
        image=image,
        shared_product=shared_product,
        shared_outfit=shared_outfit,
        story_reply=story_reply,
    )
    return dm


def mark_conversation_as_read(reader, partner):
    """
    Marks all incoming messages from partner to reader as read.
    """
    updated_count = DirectMessage.objects.filter(
        sender=partner,
        recipient=reader,
        is_read=False
    ).update(is_read=True)
    return updated_count
