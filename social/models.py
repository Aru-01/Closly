from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from closet.models import ClosetItem

User = get_user_model()

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
    image = models.ImageField(_('outfit picture'), upload_to='today_outfits/')
    caption = models.TextField(_('caption'), blank=True, default='')
    visibility = models.CharField(_('visibility'), max_length=10, choices=VISIBILITY_CHOICES, default='public')
    tagged_items = models.ManyToManyField(ClosetItem, blank=True, related_name='tagged_in_outfits')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('today outfit')
        verbose_name_plural = _('today outfits')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email}'s outfit on {self.created_at.strftime('%Y-%m-%d')}"

    @property
    def likes_count(self):
        return self.likes.count()


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


class DirectMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    content = models.TextField(_('message content'))
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"From {self.sender.email} to {self.recipient.email} at {self.created_at}"
