import logging
from datetime import timedelta
from django.utils import timezone
from social.models import Story, StoryView, StoryLike

logger = logging.getLogger(__name__)


def record_story_view(user, story_id: int):
    """
    Records a unique viewer for a 24-hour story.
    """
    story = Story.objects.get(id=story_id, is_active=True)
    if story.user != user:
        view, created = StoryView.objects.get_or_create(story=story, viewer=user)
        return story, created
    return story, False


def toggle_story_like(user, story_id: int):
    """
    Toggles a like reaction on an active 24-hour story.
    """
    story = Story.objects.get(id=story_id, is_active=True)
    like = StoryLike.objects.filter(story=story, user=user).first()
    if like:
        like.delete()
        is_liked = False
    else:
        StoryLike.objects.create(story=story, user=user)
        is_liked = True
    return story, is_liked


def expire_stale_stories():
    """
    Background worker function that marks expired 24-hour stories as inactive.
    """
    now = timezone.now()
    count = Story.objects.filter(is_active=True, expires_at__lte=now).update(is_active=False)
    logger.info(f"Story cleanup: Expired {count} stale stories.")
    return count
