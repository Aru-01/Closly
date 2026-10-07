from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
import decimal
import uuid
import os

User = get_user_model()


def closet_item_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or '.jpg'
    return f"closet_items/{uuid.uuid4().hex}{ext}"


def fit_check_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or '.jpg'
    user_id = getattr(instance, 'user_id', 'common')
    return f"fit_checks/{user_id}/{uuid.uuid4().hex}{ext}"


class FitCheck(models.Model):
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('tagged', 'Tagged'),
        ('dedupe_hit', 'Dedupe Hit'),
        ('failed', 'Failed'),
        ('failed_budget', 'Failed Budget'),
        ('nsfw_blocked', 'NSFW Blocked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='fit_checks',
        verbose_name=_('user')
    )
    photo = models.FileField(
        _('fit check photo'),
        upload_to=fit_check_upload_path,
        max_length=500,
        blank=True,
        null=True
    )
    photo_sha256 = models.CharField(_('photo SHA-256'), max_length=64, db_index=True)
    status = models.CharField(_('status'), max_length=30, choices=STATUS_CHOICES, default='uploaded')
    nsfw_score = models.FloatField(_('NSFW score'), null=True, blank=True)
    raw_tagging = models.JSONField(_('raw tagging data'), blank=True, null=True, default=dict)
    tagging_model = models.CharField(_('tagging model'), max_length=100, blank=True, default='')
    provider = models.CharField(_('AI provider'), max_length=50, blank=True, default='')
    cost_cents = models.DecimalField(
        _('cost cents'),
        max_digits=8,
        decimal_places=4,
        default=decimal.Decimal('0.0000')
    )
    error_code = models.CharField(_('error code'), max_length=50, blank=True, default='')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, db_index=True)
    tagged_at = models.DateTimeField(_('tagged at'), blank=True, null=True)
    deleted_at = models.DateTimeField(_('deleted at'), blank=True, null=True)

    class Meta:
        verbose_name = _('fit check')
        verbose_name_plural = _('fit checks')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'photo_sha256']),
        ]

    def __str__(self):
        return f"FitCheck {self.id} ({self.status}) - {self.user}"

    def delete(self, *args, **kwargs):
        if self.photo and hasattr(self.photo, 'storage'):
            storage, path = self.photo.storage, self.photo.name
            super().delete(*args, **kwargs)
            if path and storage.exists(path):
                storage.delete(path)
        else:
            super().delete(*args, **kwargs)


class ClosetItem(models.Model):
    CATEGORY_CHOICES = [
        ('top', 'Top'),
        ('bottom', 'Bottom'),
        ('shoes', 'Shoes'),
        ('dresses_outerwear', 'Dresses & Outerwear'),
        ('accessories', 'Accessories'),
        ('other', 'Other'),
    ]

    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('scan', 'AI Scan'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='closet_items',
        verbose_name=_('user')
    )
    fit_check = models.ForeignKey(
        FitCheck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closet_items',
        verbose_name=_('associated fit check')
    )
    name = models.CharField(_('cloth name'), max_length=150)
    category = models.CharField(_('category'), max_length=30, choices=CATEGORY_CHOICES)
    color = models.CharField(_('color'), max_length=50, blank=True, default='')
    brand = models.CharField(_('brand'), max_length=100, blank=True, default='')
    size = models.CharField(_('size'), max_length=20, blank=True, default='')
    price = models.DecimalField(
        _('price'),
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(decimal.Decimal('0.00'))]
    )
    currency = models.CharField(_('currency'), max_length=10, default='EUR')
    style_vibe = models.CharField(_('style vibe'), max_length=100, blank=True, default='')
    pattern = models.CharField(_('pattern'), max_length=50, blank=True, default='')
    style_tags = models.JSONField(_('style tags'), default=list, blank=True)
    occasion = models.JSONField(_('occasion'), default=list, blank=True)
    fit = models.CharField(_('fit'), max_length=50, blank=True, default='')
    attr_sentence_en = models.CharField(_('attribute sentence en'), max_length=255, blank=True, default='')
    confidence = models.FloatField(_('confidence'), null=True, blank=True)
    source = models.CharField(_('source'), max_length=20, choices=SOURCE_CHOICES, default='manual')
    photo_sha256 = models.CharField(_('photo SHA-256'), max_length=64, blank=True, default='', db_index=True)
    image = models.ImageField(
        _('cloth picture'),
        upload_to=closet_item_upload_path,
        max_length=500,
        blank=True,
        null=True
    )
    times_worn = models.PositiveIntegerField(_('times worn'), default=0)
    last_worn_at = models.DateTimeField(_('last worn at'), blank=True, null=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('closet item')
        verbose_name_plural = _('closet items')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    def delete(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'storage'):
            storage, path = self.image.storage, self.image.name
            super().delete(*args, **kwargs)
            if path and storage.exists(path):
                # Ensure no other ClosetItem references the exact same file
                if not ClosetItem.objects.filter(image=path).exists():
                    storage.delete(path)
        else:
            super().delete(*args, **kwargs)

    @property
    def per_wear_cost(self):
        if self.times_worn > 0:
            return float(round(self.price / decimal.Decimal(self.times_worn), 2))
        return float(self.price)


class LLMCostLog(models.Model):
    """
    Audit log for AI token usage, latency, and estimated cost in EUR cents (C-05, Spec §3.1).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='llm_cost_logs',
        null=True,
        blank=True,
        verbose_name=_('user')
    )
    fit_check = models.ForeignKey(
        FitCheck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cost_logs',
        verbose_name=_('fit check')
    )
    task = models.CharField(_('task'), max_length=50, default='photo_analysis')
    provider = models.CharField(_('provider'), max_length=50, default='openai')
    model = models.CharField(_('model'), max_length=100)
    input_tokens = models.PositiveIntegerField(_('input tokens'), default=0)
    output_tokens = models.PositiveIntegerField(_('output tokens'), default=0)
    cost_cents = models.DecimalField(
        _('estimated cost (EUR cents)'),
        max_digits=8,
        decimal_places=4,
        default=decimal.Decimal('0.0000')
    )
    latency_ms = models.PositiveIntegerField(_('latency ms'), default=0)
    success = models.BooleanField(_('success'), default=True)
    error_code = models.CharField(_('error code'), max_length=50, blank=True, default='')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('LLM cost log')
        verbose_name_plural = _('LLM cost logs')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['task', '-created_at']),
        ]

    def __str__(self):
        status = 'success' if self.success else f"failed ({self.error_code})"
        return f"LLMCostLog {self.task} by {self.user} - {self.model} ({status}, {self.cost_cents} ct)"


