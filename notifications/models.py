from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class Notification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [
        ('outfit_like', 'Outfit Liked'),
        ('new_follower', 'New Follower'),
        ('direct_message', 'Direct Message'),
        ('points_earned', 'Points Earned'),
        ('points_expired', 'Points Expired'),
        ('tier_upgrade', 'Tier Upgrade'),
        ('closet_item_added', 'Closet Item Added'),
        ('outfit_shared', 'Outfit Shared'),
        ('story_reaction', 'Story Reaction'),
        ('system', 'System Announcement'),
    ]

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('recipient')
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
        verbose_name=_('sender')
    )
    notification_type = models.CharField(
        _('notification type'),
        max_length=30,
        choices=NOTIFICATION_TYPE_CHOICES
    )
    title = models.CharField(_('title'), max_length=255)
    message = models.TextField(_('message'))
    data = models.JSONField(_('data'), default=dict, blank=True)
    is_read = models.BooleanField(_('is read'), default=False)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('notification')
        verbose_name_plural = _('notifications')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} for {self.recipient.email} - Read: {self.is_read}"
