import uuid
import decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings


class Brand(models.Model):
    """
    Brand entity registry.
    Manages anchor and indie brand information, affiliate/Shopify source configuration,
    commission, validation windows, consent tracking, and sync health.
    """
    KIND_AWIN = 'awin'
    KIND_RAKUTEN = 'rakuten'
    KIND_SHOPIFY = 'shopify_public'
    KIND_MYC_FEED = 'myc_feed'
    KIND_CHOICES = [
        (KIND_AWIN, 'Awin'),
        (KIND_RAKUTEN, 'Rakuten'),
        (KIND_SHOPIFY, 'Shopify Public'),
        (KIND_MYC_FEED, 'MYC Feed'),
    ]

    TIER_ANCHOR = 'anchor'
    TIER_INDIE = 'indie'
    TIER_CHOICES = [
        (TIER_ANCHOR, 'Anchor'),
        (TIER_INDIE, 'Indie'),
    ]

    STATUS_APPLIED = 'applied'
    STATUS_LIVE = 'live'
    STATUS_ACTIVE = STATUS_LIVE  # Developer friendly alias
    STATUS_PAUSED = 'paused'
    STATUS_ENDED = 'ended'
    STATUS_CHOICES = [
        (STATUS_APPLIED, 'Applied'),
        (STATUS_LIVE, 'Live'),
        (STATUS_PAUSED, 'Paused'),
        (STATUS_ENDED, 'Ended'),
    ]

    name = models.CharField(_('brand name'), max_length=255, db_index=True)
    slug = models.SlugField(_('brand slug'), max_length=255, unique=True, db_index=True)
    kind = models.CharField(_('source kind'), max_length=30, choices=KIND_CHOICES, default=KIND_AWIN)
    external_id = models.CharField(_('external ID (MID/Merchant ID)'), max_length=100, blank=True, default='')
    feed_url = models.URLField(_('feed URL'), max_length=2000, blank=True, default='')
    config = models.JSONField(_('brand configuration'), default=dict, blank=True)
    currency = models.CharField(_('currency'), max_length=10, default='EUR')
    tier = models.CharField(_('brand tier'), max_length=20, choices=TIER_CHOICES, default=TIER_INDIE)
    status = models.CharField(_('status'), max_length=20, choices=STATUS_CHOICES, default=STATUS_LIVE, db_index=True)

    # Consent and legal fields (indie ingestion requirements)
    consent_kind = models.CharField(_('consent kind'), max_length=50, blank=True, default='')
    consent_at = models.DateTimeField(_('consent timestamp'), null=True, blank=True)
    consent_ref = models.CharField(_('consent reference'), max_length=255, blank=True, default='')

    # Commercials
    commission_pct = models.DecimalField(_('commission percentage'), max_digits=5, decimal_places=2, default=0.00)
    validation_window_days = models.PositiveIntegerField(_('validation window (days)'), default=30)

    # Sync metrics
    last_sync_at = models.DateTimeField(_('last sync at'), null=True, blank=True)
    last_success_at = models.DateTimeField(_('last success at'), null=True, blank=True)
    fail_count = models.PositiveIntegerField(_('consecutive failure count'), default=0)

    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('brand')
        verbose_name_plural = _('brands')
        ordering = ['name']
        indexes = [
            models.Index(fields=['status', 'tier']),
            models.Index(fields=['kind', 'status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.kind} - {self.status})"


class AffiliateProduct(models.Model):
    """
    Products imported from affiliate networks and partner brand feeds.
    Users browse these in the newsfeed and For You feed. On 'Buy', outbound click attribution
    is recorded and user is redirected via tracked affiliate deep link.
    """

    # ------------------------------------------------------------------ #
    # Core identifiers
    # ------------------------------------------------------------------ #
    SOURCE_AWIN = 'awin'
    SOURCE_RAKUTEN = 'rakuten'
    SOURCE_SHOPIFY = 'shopify'
    SOURCE_MYC_FEED = 'myc_feed'
    SOURCE_CHOICES = [
        (SOURCE_AWIN, 'Awin'),
        (SOURCE_RAKUTEN, 'Rakuten'),
        (SOURCE_SHOPIFY, 'Shopify'),
        (SOURCE_MYC_FEED, 'MYC Feed'),
    ]
    source = models.CharField(
        _('affiliate source'),
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_AWIN,
        db_index=True,
        help_text=_("Which affiliate network or feed source this product comes from"),
    )

    aw_product_id = models.CharField(
        _('network product ID'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Unique product ID from network or feed"),
    )

    brand_ref = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_('brand reference'),
        help_text=_("Foreign key reference to registered Brand entity"),
    )

    # ------------------------------------------------------------------ #
    # Product info
    # ------------------------------------------------------------------ #
    name = models.CharField(_('product name'), max_length=500)
    brand = models.CharField(_('brand'), max_length=255, db_index=True)
    description = models.TextField(_('description'), blank=True, default='')
    colour = models.CharField(_('colour'), max_length=100, blank=True, default='')
    color_primary = models.CharField(_('primary color normalized'), max_length=100, blank=True, default='', db_index=True)
    category = models.CharField(_('raw category'), max_length=255, blank=True, db_index=True)
    category_norm = models.CharField(_('normalized category'), max_length=255, blank=True, default='', db_index=True)

    GENDER_WOMEN = 'women'
    GENDER_MEN = 'men'
    GENDER_UNISEX = 'unisex'
    GENDER_CHOICES = [
        (GENDER_WOMEN, 'Women'),
        (GENDER_MEN, 'Men'),
        (GENDER_UNISEX, 'Unisex'),
    ]
    gender = models.CharField(
        _('gender target'),
        max_length=20,
        choices=GENDER_CHOICES,
        default=GENDER_UNISEX,
        db_index=True,
    )

    sizes = models.JSONField(
        _('available sizes'),
        default=list,
        blank=True,
        help_text=_("List of normalized available size strings"),
    )

    advertiser_name = models.CharField(_('advertiser name'), max_length=255, blank=True, default='')

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #
    price = models.DecimalField(_('sale price'), max_digits=10, decimal_places=2, default=0)
    rrp_price = models.DecimalField(
        _('RRP / original price'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Original retail price before discount"),
    )
    currency = models.CharField(_('currency'), max_length=10, default='EUR', db_index=True)

    image_url = models.URLField(_('image URL'), max_length=2000, blank=True, default='')
    additional_image_urls = models.JSONField(
        _('additional image URLs'),
        default=list,
        blank=True,
        help_text=_("List of additional product gallery images"),
    )
    cdn_image_url = models.URLField(
        _('CDN replicated image URL'),
        max_length=2000,
        blank=True,
        default='',
        help_text=_("Locally stored/CDN replicated image URL (Audit CF-18)"),
    )
    image_hash = models.CharField(
        _('image SHA-256 hash'),
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text=_("SHA-256 hash of image content for deduplication and integrity"),
    )
    image_replicated_at = models.DateTimeField(
        _('image replicated at'),
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------ #
    # Links
    # ------------------------------------------------------------------ #
    aw_deep_link = models.URLField(
        _('affiliate tracking link'),
        max_length=2000,
        help_text=_("Tracked affiliate URL template"),
    )
    merchant_deep_link = models.URLField(
        _('merchant direct link'),
        max_length=2000,
        blank=True,
        default='',
        help_text=_("Direct link to product on brand website (fallback / direct UTM)"),
    )

    # ------------------------------------------------------------------ #
    # Status & Staleness tracking
    # ------------------------------------------------------------------ #
    is_active = models.BooleanField(_('is active'), default=True, db_index=True)
    in_stock = models.BooleanField(_('in stock'), default=True, db_index=True)
    miss_count = models.PositiveIntegerField(
        _('consecutive missing sync runs'),
        default=0,
        db_index=True,
        help_text=_("Number of consecutive sync runs where product was absent (2-run grace period)"),
    )
    content_hash = models.CharField(
        _('payload content hash'),
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text=_("SHA-256 hash of core fields to avoid redundant DB writes on unchanged runs"),
    )

    # ------------------------------------------------------------------ #
    # Timestamps
    # ------------------------------------------------------------------ #
    first_seen_at = models.DateTimeField(_('first seen at'), null=True, blank=True)
    last_seen_at = models.DateTimeField(_('last seen at'), null=True, blank=True, db_index=True)
    price_checked_at = models.DateTimeField(_('price checked at'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True, db_index=True)

    class Meta:
        verbose_name = _('affiliate product')
        verbose_name_plural = _('affiliate products')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['brand', 'is_active']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['category_norm', 'is_active']),
            models.Index(fields=['gender', 'is_active']),
            models.Index(fields=['price', 'is_active']),
            models.Index(fields=['currency', 'is_active']),
            models.Index(fields=['brand_ref', 'is_active']),
            models.Index(fields=['in_stock', 'is_active']),
            models.Index(fields=['content_hash']),
            models.Index(fields=['source', 'last_seen_at']),
        ]

    def __str__(self):
        return f"{self.name} — {self.brand} ({self.currency} {self.price})"

    @property
    def discount_percent(self):
        """Calculate discount % if RRP is available."""
        if self.rrp_price and self.rrp_price > 0 and self.price < self.rrp_price:
            return round(((self.rrp_price - self.price) / self.rrp_price) * 100)
        return None


class ProductClick(models.Model):
    """
    Attribution click record.
    Tracks outbound clicks to affiliate networks / partner merchants with unique click_ref UUID
    passed as SubID (AWIN clickref / Rakuten u1 / Shopify UTM) to join future conversions.
    """
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.PROTECT,
        related_name='clicks',
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_clicks',
    )
    click_ref = models.UUIDField(
        _('click reference UUID'),
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_("Unique click reference token passed to affiliate network for conversion attribution"),
    )
    surface = models.CharField(
        _('click surface'),
        max_length=50,
        default='feed',
        db_index=True,
        help_text=_("Surface where click originated: feed, newsfeed, detail, saved, dm, sprint"),
    )
    session_id = models.CharField(
        _('session ID'),
        max_length=100,
        blank=True,
        default='',
    )
    user_agent_hash = models.CharField(
        _('user agent hash'),
        max_length=64,
        blank=True,
        default='',
    )
    ip_prefix = models.CharField(
        _('anonymized IP prefix'),
        max_length=45,
        blank=True,
        default='',
        help_text=_("Anonymized network prefix (e.g. /24 for IPv4, /48 for IPv6) — no raw PII"),
    )
    idempotency_key = models.CharField(
        _('idempotency key'),
        max_length=100,
        blank=True,
        default='',
        db_index=True,
    )
    clicked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('product click')
        verbose_name_plural = _('product clicks')
        ordering = ['-clicked_at']
        indexes = [
            models.Index(fields=['user', 'clicked_at']),
            models.Index(fields=['product', 'clicked_at']),
        ]

    def __str__(self):
        return f"Click [{self.click_ref}] on {self.product.name} at {self.clicked_at}"


class ProductFavorite(models.Model):
    """
    Tracks products saved / loved / wishlisted by users.
    """
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.PROTECT,
        related_name='favorites',
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='favorite_products',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('product favorite')
        verbose_name_plural = _('product favorites')
        ordering = ['-created_at']
        unique_together = ('product', 'user')

    def __str__(self):
        return f"{self.user} loves {self.product.name}"


class CatalogSyncRun(models.Model):
    """
    Audit and safety log for every catalog ingestion run.
    Guards against catalogue wipes, zero-delta failures, and tracks row changes.
    """
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_GUARDED = 'guarded'
    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_GUARDED, 'Guarded (Safety threshold triggered)'),
    ]

    feed_id = models.CharField(_('feed identifier'), max_length=100, db_index=True)
    source = models.CharField(_('source network'), max_length=30, blank=True, default='')
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_runs',
    )
    started_at = models.DateTimeField(_('started at'), auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(_('finished at'), null=True, blank=True)
    rows_seen = models.PositiveIntegerField(_('rows seen'), default=0)
    rows_new = models.PositiveIntegerField(_('new rows'), default=0)
    rows_changed = models.PositiveIntegerField(_('changed rows'), default=0)
    rows_unchanged = models.PositiveIntegerField(_('unchanged rows'), default=0)
    rows_deactivated = models.PositiveIntegerField(_('deactivated rows'), default=0)
    error_count = models.PositiveIntegerField(_('error count'), default=0)
    status = models.CharField(
        _('sync status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RUNNING,
        db_index=True,
    )
    notes = models.TextField(_('notes / logs'), blank=True, default='')

    class Meta:
        verbose_name = _('catalog sync run')
        verbose_name_plural = _('catalog sync runs')
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.feed_id} [{self.status}] at {self.started_at}"


class FeedAttributeMapping(models.Model):
    """
    Normalizes raw feed attributes (category strings, gender keywords, color names)
    at ingestion time without slow runtime regex scans.
    """
    source = models.CharField(_('source network'), max_length=50, default='all', db_index=True)
    field = models.CharField(_('target field'), max_length=50, db_index=True)  # category, gender, color
    raw_value = models.CharField(_('raw feed value'), max_length=255, db_index=True)
    normalized_value = models.CharField(_('normalized value'), max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('feed attribute mapping')
        verbose_name_plural = _('feed attribute mappings')
        unique_together = ('source', 'field', 'raw_value')

    def __str__(self):
        return f"[{self.source}] {self.field}: '{self.raw_value}' -> '{self.normalized_value}'"


class Event(models.Model):
    """
    Captures raw user behavior events for discovery ranking, CTR analytics,
    and taste scoring (backend behavioral foundation without external LLM).
    """
    CLASS_IMPRESSION = 'impression'
    CLASS_INTERACTION = 'interaction'
    CLASS_CONVERSION = 'conversion'
    CLASS_CHOICES = [
        (CLASS_IMPRESSION, 'Impression'),
        (CLASS_INTERACTION, 'Interaction'),
        (CLASS_CONVERSION, 'Conversion'),
    ]

    TYPE_IMPRESSION = 'impression'
    TYPE_DETAIL_VIEW = 'detail_view'
    TYPE_LIKE = 'like'
    TYPE_SKIP = 'skip'
    TYPE_SAVE = 'save'
    TYPE_CLICK_OUT = 'click_out'
    TYPE_FAVORITE = 'favorite'
    TYPE_CHOICES = [
        (TYPE_IMPRESSION, 'Impression'),
        (TYPE_DETAIL_VIEW, 'Detail View'),
        (TYPE_LIKE, 'Like'),
        (TYPE_SKIP, 'Skip'),
        (TYPE_SAVE, 'Save'),
        (TYPE_CLICK_OUT, 'Click Out (Buy)'),
        (TYPE_FAVORITE, 'Favorite'),
    ]

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='affiliate_events',
        verbose_name=_('user'),
    )
    event_class = models.CharField(
        _('event class'),
        max_length=30,
        choices=CLASS_CHOICES,
        default=CLASS_INTERACTION,
        db_index=True,
    )
    event_type = models.CharField(
        _('event type'),
        max_length=30,
        choices=TYPE_CHOICES,
        db_index=True,
    )
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name=_('product'),
    )
    source = models.CharField(
        _('source surface'),
        max_length=50,
        default='for_you',
        help_text=_("Surface where event occurred: for_you, newsfeed, detail, saved, sprint"),
    )
    feed_page = models.PositiveIntegerField(_('feed page number'), null=True, blank=True)
    dwell_ms = models.PositiveIntegerField(_('dwell time (ms)'), null=True, blank=True)
    berlin_day = models.DateField(_('Berlin date'), db_index=True)
    client_ts = models.DateTimeField(_('client timestamp'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('user behavior event')
        verbose_name_plural = _('user behavior events')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['user', 'event_type', 'created_at']),
            models.Index(fields=['product', 'event_type']),
            models.Index(fields=['berlin_day', 'event_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product', 'berlin_day', 'event_type'],
                condition=models.Q(event_type='impression'),
                name='unique_user_product_day_impression',
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.event_type} on {self.product_id} ({self.berlin_day})"


class FeedImpressionsDaily(models.Model):
    """
    Daily aggregated impression and interaction metrics for products in feeds.
    Used for P@10, Aha-rate, and feed performance evaluation.
    """
    berlin_day = models.DateField(_('Berlin date'), db_index=True)
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.CASCADE,
        related_name='daily_impressions',
    )
    brand_name = models.CharField(_('brand name'), max_length=255, db_index=True)
    impressions_count = models.PositiveIntegerField(_('viewed impressions count'), default=0)
    detail_views_count = models.PositiveIntegerField(_('detail views count'), default=0)
    saves_count = models.PositiveIntegerField(_('saves count'), default=0)
    clicks_count = models.PositiveIntegerField(_('click-outs count'), default=0)
    likes_count = models.PositiveIntegerField(_('likes count'), default=0)
    skips_count = models.PositiveIntegerField(_('skips count'), default=0)

    class Meta:
        verbose_name = _('feed impressions daily')
        verbose_name_plural = _('feed impressions daily')
        unique_together = ('berlin_day', 'product')
        indexes = [
            models.Index(fields=['berlin_day', 'brand_name']),
        ]

    def __str__(self):
        return f"{self.berlin_day}: {self.product_id} ({self.impressions_count} imps, {self.clicks_count} clicks)"


class Conversion(models.Model):
    """
    Affiliate Purchase Conversion & Transaction attribution model (Audit CF-30).
    Captures postback/webhook and polled transactions from affiliate networks (AWIN, Rakuten, Shopify).
    Preserves idempotent ledger linkage between outbound click (click_ref) and merchant transaction.
    """
    SOURCE_AWIN = 'awin'
    SOURCE_RAKUTEN = 'rakuten'
    SOURCE_SHOPIFY = 'shopify'
    SOURCE_CHOICES = [
        (SOURCE_AWIN, 'Awin'),
        (SOURCE_RAKUTEN, 'Rakuten'),
        (SOURCE_SHOPIFY, 'Shopify'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_DECLINED = 'declined'
    STATUS_DELETED = 'deleted'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_DELETED, 'Deleted'),
    ]

    conversion_id = models.CharField(_('network transaction ID'), max_length=128, db_index=True)
    source = models.CharField(_('affiliate source'), max_length=30, choices=SOURCE_CHOICES, default=SOURCE_AWIN, db_index=True)

    # Attribution linkage
    click = models.ForeignKey(
        ProductClick,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversions',
        help_text=_("Linked outbound product click record"),
    )
    click_ref = models.UUIDField(
        _('click reference UUID'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Raw click reference token passed to network"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affiliate_conversions',
        help_text=_("User who generated the click/conversion"),
    )
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversions',
        help_text=_("Purchased product in catalog if identifiable"),
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversions',
        help_text=_("Merchant brand associated with this transaction"),
    )

    advertiser_id = models.CharField(_('advertiser / merchant ID'), max_length=100, blank=True, default='', db_index=True)
    order_reference = models.CharField(_('merchant order reference'), max_length=255, blank=True, default='', db_index=True)

    status = models.CharField(_('conversion status'), max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    sale_amount = models.DecimalField(_('sale amount'), max_digits=12, decimal_places=2, default=decimal.Decimal('0.00'))
    commission_amount = models.DecimalField(_('commission amount'), max_digits=12, decimal_places=2, default=decimal.Decimal('0.00'))
    currency = models.CharField(_('currency code'), max_length=10, default='EUR', db_index=True)

    transaction_date = models.DateTimeField(_('transaction date'), null=True, blank=True)
    validation_date = models.DateTimeField(_('validation date'), null=True, blank=True)

    # Rewards linkage
    reward_claimed = models.BooleanField(_('reward points claimed'), default=False)
    reward_transaction = models.ForeignKey(
        'rewards.RewardPointTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affiliate_conversions',
        help_text=_("Linked reward transaction when purchase points are awarded"),
    )

    raw_payload = models.JSONField(_('raw webhook payload'), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('affiliate conversion')
        verbose_name_plural = _('affiliate conversions')
        ordering = ['-transaction_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'conversion_id'],
                name='unique_source_conversion_id',
            )
        ]
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['order_reference']),
            models.Index(fields=['click_ref']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.source.upper()} Conversion {self.conversion_id} ({self.status}) - {self.sale_amount} {self.currency}"
