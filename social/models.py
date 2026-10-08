from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
import uuid
import os
from closet.models import ClosetItem

User = get_user_model()


def today_outfit_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or '.jpg'
    return f"today_outfits/{uuid.uuid4().hex}{ext}"


class TodayOutfit(models.Model):
    VISIBILITY_CHOICES = [
        ('private', 'Private (Only Me)'),
        ('public', 'Public (All Users)'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='today_outfits',
        verbose_name=_('user')
    )
    image = models.ImageField(_('outfit picture'), upload_to=today_outfit_upload_path, max_length=500)
    caption = models.TextField(_('caption'), blank=True, default='')
    visibility = models.CharField(_('visibility'), max_length=10, choices=VISIBILITY_CHOICES, default='public')
    style_category = models.CharField(_('style category'), max_length=50, blank=True, default='')
    weather_tag = models.CharField(_('weather tag'), max_length=50, blank=True, default='')
    tagged_items = models.ManyToManyField(ClosetItem, blank=True, related_name='tagged_in_outfits')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('today outfit')
        verbose_name_plural = _('today outfits')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visibility', '-created_at']),
            models.Index(fields=['user', 'visibility', '-created_at']),
            models.Index(fields=['style_category', 'visibility', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.email}'s outfit on {self.created_at.strftime('%Y-%m-%d')}"

    @property
    def likes_count(self):
        if hasattr(self, '_likes_count'):
            return self._likes_count
        if self._state.adding:
            return 0
        if 'likes' in getattr(self, '_prefetched_objects_cache', {}):
            return len(self.likes.all())
        return self.likes.count()


class OutfitImage(models.Model):
    """
    Multiple images support for TodayOutfit (up to 4 images per outfit).
    Preserves carousel order and full high-resolution image uploads.
    """
    outfit = models.ForeignKey(
        TodayOutfit,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_('outfit')
    )
    image = models.ImageField(_('outfit picture'), upload_to=today_outfit_upload_path, max_length=500)
    order = models.PositiveSmallIntegerField(_('display order'), default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('outfit image')
        verbose_name_plural = _('outfit images')
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['outfit', 'order']),
        ]

    def __str__(self):
        return f"Image {self.id} for outfit {self.outfit_id} (order={self.order})"


class OutfitLike(models.Model):
    outfit = models.ForeignKey(TodayOutfit, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='outfit_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('outfit', 'user')

    def __str__(self):
        return f"{self.user.email} liked outfit {self.outfit.id}"


class UserFollow(models.Model):
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_set')
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers_set')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')

    def __str__(self):
        return f"{self.follower.email} follows {self.following.email}"


from django.utils import timezone
from datetime import timedelta

def story_image_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or '.jpg'
    return f"stories/{uuid.uuid4().hex}{ext}"


def chat_attachment_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or '.jpg'
    return f"chat_attachments/{uuid.uuid4().hex}{ext}"


class Story(models.Model):
    """
    24-hour disappearing user stories with image, caption, view tracking, and loves.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='stories',
        verbose_name=_('user')
    )
    image = models.ImageField(_('story picture'), upload_to=story_image_upload_path, max_length=500)
    caption = models.CharField(_('caption'), max_length=500, blank=True, default='')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    expires_at = models.DateTimeField(_('expires at'), blank=True, null=True, db_index=True)
    is_active = models.BooleanField(_('is active'), default=True, db_index=True)

    class Meta:
        verbose_name = _('story')
        verbose_name_plural = _('stories')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active', '-created_at']),
            models.Index(fields=['expires_at', 'is_active']),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email}'s story at {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def views_count(self):
        if hasattr(self, '_views_count'):
            return self._views_count
        if self._state.adding:
            return 0
        if 'views' in getattr(self, '_prefetched_objects_cache', {}):
            return len([v for v in self.views.all() if v.viewer_id != self.user_id])
        return self.views.exclude(viewer=self.user).count()

    @property
    def loves_count(self):
        if hasattr(self, '_loves_count'):
            return self._loves_count
        if self._state.adding:
            return 0
        if 'likes' in getattr(self, '_prefetched_objects_cache', {}):
            return len([l for l in self.likes.all() if l.user_id != self.user_id])
        return self.likes.exclude(user=self.user).count()


class StoryView(models.Model):
    """
    Tracks which users viewed a story.
    """
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='views')
    viewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='viewed_stories')
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('story', 'viewer')
        ordering = ['-viewed_at']

    def __str__(self):
        return f"{self.viewer.email} viewed story {self.story.id}"


class StoryLike(models.Model):
    """
    Tracks love/heart reactions on a story.
    """
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='liked_stories')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('story', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} loved story {self.story.id}"


class DirectMessage(models.Model):
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text Message'),
        ('image', 'Image Attachment'),
        ('product', 'Shared Product'),
        ('outfit', 'Shared Outfit'),
        ('story_reply', 'Story Reply'),
    ]

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text')
    content = models.TextField(_('message content'), blank=True, default='')
    image = models.ImageField(upload_to=chat_attachment_upload_path, max_length=500, blank=True, null=True)
    shared_product = models.ForeignKey(
        'affiliate.AffiliateProduct',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shared_in_messages'
    )
    shared_outfit = models.ForeignKey(
        TodayOutfit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shared_in_messages'
    )
    story_reference = models.ForeignKey(
        Story,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replied_in_messages'
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        return f"[{self.message_type}] From {self.sender.email} to {self.recipient.email} at {self.created_at}"


class UserBlock(models.Model):
    """
    Bilateral block mechanism between users per DSA and App Store guidelines.
    When user A blocks user B:
    - User B cannot see user A's profile, outfits, stories, feeds, or followers.
    - User B cannot message, follow, or interact with user A.
    - Any existing follow connection between them is dissolved.
    """
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocking_set')
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_by_set')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('user block')
        verbose_name_plural = _('user blocks')
        unique_together = ('blocker', 'blocked')
        indexes = [
            models.Index(fields=['blocker', 'blocked']),
        ]

    def __str__(self):
        return f"{self.blocker.email} blocked {self.blocked.email}"


class ContentReport(models.Model):
    """
    DSA Article 16/17 compliant user reporting queue.
    Allows users to report outfits, stories, messages, and user profiles.
    """
    TARGET_TYPE_CHOICES = [
        ('outfit', 'Today Outfit'),
        ('story', 'Story'),
        ('user', 'User Profile'),
        ('message', 'Direct Message'),
    ]

    REASON_CHOICES = [
        ('spam', 'Spam / Commercial advertising'),
        ('harassment', 'Harassment / Hate speech'),
        ('nudity', 'Nudity / Sexual content'),
        ('violence', 'Violence / Self-harm'),
        ('copyright', 'Copyright infringement'),
        ('impersonation', 'Impersonation'),
        ('other', 'Other violation'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('investigating', 'Investigating'),
        ('resolved', 'Action Taken'),
        ('dismissed', 'Dismissed / False Report'),
    ]

    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_reports')
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    target_id = models.CharField(max_length=100)
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    details = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    moderator_notes = models.TextField(blank=True, default='')
    action_taken = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('content report')
        verbose_name_plural = _('content reports')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f"Report #{self.id} on {self.target_type}:{self.target_id} by {self.reporter.email} ({self.status})"


def get_blocked_user_ids(user):
    """
    Returns set of user IDs where user blocked someone OR was blocked by someone (bilateral block).
    """
    if not user or not user.is_authenticated:
        return set()
    blocking = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocked_by = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return set(blocking).union(set(blocked_by))

