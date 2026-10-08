import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class LedgerAccount(models.Model):
    """
    Double-entry ledger account (SR-08).
    Accounts can be user-owned (user_available) or system-level (liability, revenue, expense).
    """
    ACCOUNT_KINDS = [
        ('user_available', 'User Available Balance'),
        ('points_liability_control', 'Points Liability Control'),
        ('awin_receivable', 'AWIN Affiliate Receivable'),
        ('boutique_receivable', 'Boutique Receivable'),
        ('commission_revenue', 'Commission Revenue'),
        ('marketing_expense', 'Marketing / Referral / Activity Expense'),
        ('redemption_clearing', 'Redemption Clearing'),
        ('breakage_income', 'Breakage / Expiration Income'),
        ('fraud_writeoff', 'Fraud Write-off'),
    ]

    kind = models.CharField(max_length=40, choices=ACCOUNT_KINDS)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='ledger_accounts',
        verbose_name=_('user')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('ledger account')
        verbose_name_plural = _('ledger accounts')
        constraints = [
            models.CheckConstraint(
                check=(
                    (models.Q(kind='user_available') & models.Q(user__isnull=False)) |
                    (~models.Q(kind='user_available') & models.Q(user__isnull=True))
                ),
                name='ledger_account_user_kind_check'
            ),
            models.UniqueConstraint(
                fields=['kind', 'user'],
                condition=models.Q(user__isnull=False),
                name='unique_user_ledger_account'
            ),
            models.UniqueConstraint(
                fields=['kind'],
                condition=models.Q(user__isnull=True),
                name='unique_system_ledger_account'
            ),
        ]

    def __str__(self):
        if self.user:
            return f"LedgerAccount({self.kind}, user={self.user.email})"
        return f"LedgerAccount({self.kind}, system)"


class PointAward(models.Model):
    """
    Lifecycle and state machine of each earned award (SR-08).
    Tracks state transitions: RESERVED -> PENDING -> CONFIRMED -> AVAILABLE -> REDEEMED / EXPIRED / CLAWED_BACK.
    """
    AWARD_TYPES = [
        ('purchase_awin', 'Purchase AWIN Conversion'),
        ('purchase_boutique', 'Purchase Boutique Partner'),
        ('referral_signup', 'Referral Signup'),
        ('referral_active', 'Referral Activated'),
        ('weekly_goal', 'Weekly Goal'),
        ('share_look', 'Share Look Outfit'),
        ('add_closet_item', 'Add Closet Item'),
        ('manual_goodwill', 'Manual Goodwill Credit'),
    ]

    AWARD_STATES = [
        ('RESERVED', 'Reserved (Unverified Intent)'),
        ('PENDING', 'Pending Postback / Advertiser Review'),
        ('CONFIRMED', 'Confirmed (Approved)'),
        ('AVAILABLE', 'Available for Spending'),
        ('PARTIALLY_REDEEMED', 'Partially Redeemed'),
        ('REDEEMED', 'Fully Redeemed'),
        ('VOID', 'Voided / Cancelled'),
        ('CLAWED_BACK', 'Clawed Back / Reversal'),
        ('EXPIRED', 'Expired (24 Months)'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='point_awards',
        verbose_name=_('recipient user')
    )
    award_type = models.CharField(max_length=30, choices=AWARD_TYPES)
    points_original = models.PositiveIntegerField()
    points_current = models.PositiveIntegerField()
    state = models.CharField(max_length=25, choices=AWARD_STATES, default='AVAILABLE')

    click_reference = models.CharField(max_length=120, blank=True, default='')
    conversion_reference = models.CharField(max_length=120, blank=True, default='')
    referred_user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='referred_awards_generated',
        verbose_name=_('referred user')
    )
    outfit_id = models.IntegerField(null=True, blank=True, db_index=True)

    eta_available_at = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # 24 months from available_at (SR-08)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('point award')
        verbose_name_plural = _('point awards')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['conversion_reference'],
                condition=~models.Q(conversion_reference=''),
                name='unique_point_award_conversion'
            ),
            models.UniqueConstraint(
                fields=['award_type', 'referred_user'],
                condition=models.Q(referred_user__isnull=False),
                name='unique_point_award_referred_user'
            ),
        ]

    @property
    def status(self):
        """Compatibility property mapping state to status."""
        if self.state == 'AVAILABLE':
            return 'completed'
        elif self.state in ('PENDING', 'RESERVED'):
            return 'pending'
        return self.state.lower()

    def __str__(self):
        return f"PointAward #{self.id} ({self.award_type}) - {self.points_current} pts [{self.state}] for {self.user.email}"


class LedgerTxn(models.Model):
    """
    Append-only double-entry transaction container (SR-08).
    Must strictly balance to zero across its LedgerEntry legs.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    txn_type = models.CharField(max_length=50)
    award = models.ForeignKey(
        PointAward,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='ledger_transactions'
    )
    conversion_reference = models.CharField(max_length=120, blank=True, default='')
    idempotency_key = models.CharField(max_length=150, unique=True)
    description = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_ledger_txns'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('ledger transaction')
        verbose_name_plural = _('ledger transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f"LedgerTxn {self.id} ({self.txn_type}): {self.description}"


class LedgerEntry(models.Model):
    """
    Individual leg in a double-entry transaction (SR-08).
    Positive points = credit, negative points = debit.
    """
    txn = models.ForeignKey(
        LedgerTxn,
        on_delete=models.CASCADE,
        related_name='entries'
    )
    account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name='entries'
    )
    points = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('ledger entry')
        verbose_name_plural = _('ledger entries')
        constraints = [
            models.CheckConstraint(
                check=~models.Q(points=0),
                name='ledger_entry_points_nonzero'
            )
        ]

    def __str__(self):
        return f"Entry ({self.account.kind}): {self.points:+d} pts"


class AwardStateLog(models.Model):
    """
    Immutable audit log of award state transitions (SR-08).
    """
    award = models.ForeignKey(
        PointAward,
        on_delete=models.CASCADE,
        related_name='state_logs'
    )
    from_state = models.CharField(max_length=25)
    to_state = models.CharField(max_length=25)
    reason = models.CharField(max_length=255, blank=True, default='')
    points_delta = models.IntegerField(default=0)
    actor = models.CharField(max_length=100, default='system')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('award state log')
        verbose_name_plural = _('award state logs')
        ordering = ['-created_at']

    def __str__(self):
        return f"StateLog Award #{self.award.id}: {self.from_state} -> {self.to_state} ({self.reason})"


class UserRewardProfile(models.Model):
    """
    Cached view of available spendable points, lifetime achievement points, and tier status.
    Maintained atomically alongside the double-entry ledger.
    - available_points: Spendable points (expire 24 months from availability or spent).
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
        help_text=_("Spendable points that expire after 24 months")
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
    User-facing statement row recording points earned, expired, reversed, or redeemed.
    Preserved for backwards compatibility with existing UI history endpoints and statements.
    """
    ACTION_CHOICES = [
        ('share_look', 'Share a Look (+120)'),
        ('invite_friend', 'Invite Friends (+200)'),
        ('make_purchase', 'Make a Purchase (+200)'),
        ('add_closet_item', 'Add to Closet (+50)'),
        ('custom_reward', 'Custom Bonus Reward'),
        ('points_expired', 'Points Expired (-X)'),
        ('points_reversal', 'Activity Points Reversal (-X)'),
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
    STATUS_CHOICES = [
        ('pending', 'Pending Activation'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='completed'
    )
    expires_at = models.DateTimeField(_('expires at'), null=True, blank=True)
    is_expired = models.BooleanField(_('is expired'), default=False)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('reward point transaction')
        verbose_name_plural = _('reward point transactions')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['action_type', 'reference_id'],
                condition=models.Q(action_type='invite_friend') & ~models.Q(reference_id=''),
                name='unique_invite_friend_reward_reference'
            ),
            models.UniqueConstraint(
                fields=['action_type', 'reference_id'],
                condition=models.Q(action_type='make_purchase') & ~models.Q(reference_id=''),
                name='unique_make_purchase_reward_reference'
            ),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.points:+d} pts ({self.action_type})"
