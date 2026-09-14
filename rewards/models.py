from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class UserRewardProfile(models.Model):
    """
    Tracks available (spendable) points, lifetime achievement points, and tier status.
    - available_points: Decreases when points expire after 60 days or are spent.
    - lifetime_points: Never decreases on expiry, permanently preserving earned tier achievement.
    """
    TIER_CHOICES = [
        ('Bronze', 'Bronze (0 - 2,000 pts)'),
        ('Silver', 'Silver (2,000 - 5,000 pts)'),
        ('Gold', 'Gold (5,000 - 10,000 pts)'),
        ('Platinum', 'Platinum (10,000 - 50,000 pts)'),
        ('Diamond', 'Diamond (50,000+ pts)'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='reward_profile',
        verbose_name=_('user')
    )
    available_points = models.PositiveIntegerField(
        _('available points'),
        default=0,
        help_text=_("Spendable points that expire after 60 days")
    )
    lifetime_points = models.PositiveIntegerField(
        _('lifetime points'),
        default=0,
        help_text=_("All-time achievement points that dictate tier level; never decreases on expiration")
    )
    current_tier = models.CharField(
        _('current tier'),
        max_length=20,
        choices=TIER_CHOICES,
        default='Bronze'
    )
    tier_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('user reward profile')
        verbose_name_plural = _('user reward profiles')

    def __str__(self):
        return f"{self.user.email} - Avail: {self.available_points} pts | Tier: {self.current_tier} ({self.lifetime_points} lifetime)"


class RewardPointTransaction(models.Model):
    """
    Ledger recording all points earned, expired, or redeemed.
    """
    ACTION_CHOICES = [
        ('share_look', 'Share a Look (+120)'),
        ('invite_friend', 'Invite Friends (+200)'),
        ('make_purchase', 'Make a Purchase (+200)'),
        ('add_closet_item', 'Add to Closet (+50)'),
        ('custom_reward', 'Custom Bonus Reward'),
        ('points_expired', 'Points Expired (-X)'),
        ('redeem_reward', 'Redeem Reward (-X)'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reward_transactions',
        verbose_name=_('user')
    )
    action_type = models.CharField(_('action type'), max_length=30, choices=ACTION_CHOICES)
    points = models.IntegerField(_('points'))
    description = models.CharField(_('description'), max_length=255)
    reference_id = models.CharField(_('reference id'), max_length=100, blank=True, default='')
    expires_at = models.DateTimeField(_('expires at'), null=True, blank=True)
    is_expired = models.BooleanField(_('is expired'), default=False)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('reward point transaction')
        verbose_name_plural = _('reward point transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email}: {self.points:+d} pts ({self.action_type})"
