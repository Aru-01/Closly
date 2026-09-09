from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
import decimal

User = get_user_model()

class ClosetItem(models.Model):
    CATEGORY_CHOICES = [
        ('top', 'Top'),
        ('bottom', 'Bottom'),
        ('shoes', 'Shoes'),
        ('dresses_outerwear', 'Dresses & Outerwear'),
        ('accessories', 'Accessories'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='closet_items',
        verbose_name=_('user')
    )
    name = models.CharField(_('cloth name'), max_length=150)
    category = models.CharField(_('category'), max_length=30, choices=CATEGORY_CHOICES)
    color = models.CharField(_('color'), max_length=50, blank=True, default='')
    brand = models.CharField(_('brand'), max_length=100, blank=True, default='')
    size = models.CharField(_('size'), max_length=20, blank=True, default='')
    price = models.DecimalField(_('price'), max_digits=10, decimal_places=2, default=0.00)
    image = models.ImageField(_('cloth picture'), upload_to='closet_items/', blank=True, null=True)
    times_worn = models.PositiveIntegerField(_('times worn'), default=0)
    last_worn_at = models.DateTimeField(_('last worn at'), blank=True, null=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('closet item')
        verbose_name_plural = _('closet items')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()}) - {self.user.email}"

    @property
    def per_wear_cost(self):
        if self.times_worn > 0:
            return float(round(self.price / decimal.Decimal(self.times_worn), 2))
        return float(self.price)
