from django.db import models
from django.utils.translation import gettext_lazy as _


class AffiliateProduct(models.Model):
    """
    Products imported from Awin affiliate network.
    Users browse these in the newsfeed. On 'Buy', they are redirected
    via aw_deep_link (the Awin tracking URL) to the brand's website.
    """

    # ------------------------------------------------------------------ #
    # Core identifiers
    # ------------------------------------------------------------------ #
    SOURCE_AWIN    = 'awin'
    SOURCE_RAKUTEN = 'rakuten'
    SOURCE_CHOICES = [
        (SOURCE_AWIN,    'Awin'),
        (SOURCE_RAKUTEN, 'Rakuten'),
    ]
    source = models.CharField(
        _('affiliate source'),
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_AWIN,
        db_index=True,
        help_text=_("Which affiliate network this product comes from"),
    )

    aw_product_id = models.CharField(
        _('network product ID'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Unique product ID from Awin or Rakuten"),
    )

    # ------------------------------------------------------------------ #
    # Product info
    # ------------------------------------------------------------------ #
    name = models.CharField(_('product name'), max_length=500)

    brand = models.CharField(_('brand'), max_length=255, db_index=True)

    description = models.TextField(_('description'), blank=True, default='')

    colour = models.CharField(_('colour'), max_length=100, blank=True, default='')

    category = models.CharField(_('category'), max_length=255, blank=True, db_index=True)

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

    currency = models.CharField(_('currency'), max_length=10, default='GBP')

    # ------------------------------------------------------------------ #
    # Images
    # ------------------------------------------------------------------ #
    image_url = models.URLField(_('image URL'), max_length=2000, blank=True, default='')

    # ------------------------------------------------------------------ #
    # Links
    # ------------------------------------------------------------------ #
    aw_deep_link = models.URLField(
        _('Awin affiliate link'),
        max_length=2000,
        help_text=_("Tracked affiliate URL — use this for the 'Buy' button"),
    )

    merchant_deep_link = models.URLField(
        _('merchant direct link'),
        max_length=2000,
        blank=True,
        default='',
        help_text=_("Direct link to the product on the brand website (no tracking)"),
    )

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    is_active = models.BooleanField(_('is active'), default=True, db_index=True)

    # ------------------------------------------------------------------ #
    # Timestamps
    # ------------------------------------------------------------------ #
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True, db_index=True)

    class Meta:
        verbose_name = _('affiliate product')
        verbose_name_plural = _('affiliate products')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['brand', 'is_active']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['price', 'is_active']),
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
    Tracks when a user taps 'Buy' on a product.
    Used for internal analytics — does NOT affect Awin tracking.
    """
    product = models.ForeignKey(
        AffiliateProduct,
        on_delete=models.CASCADE,
        related_name='clicks',
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_clicks',
    )
    clicked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('product click')
        verbose_name_plural = _('product clicks')
        ordering = ['-clicked_at']

    def __str__(self):
        return f"Click on {self.product.name} at {self.clicked_at}"
