"""
replicate_product_images.py
Management command to replicate external merchant images to S3/CDN storage (Audit CF-18).
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from affiliate.models import AffiliateProduct, Brand
from affiliate.services.image_cdn import fetch_and_replicate_image


class Command(BaseCommand):
    help = 'Download external product images, compute SHA-256 hashes, and store to S3/CDN (Audit CF-18)'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Max products to process')
        parser.add_argument('--product-id', type=int, default=None, help='Replicate single product by ID')
        parser.add_argument('--brand-slug', type=str, default=None, help='Filter by brand slug')
        parser.add_argument('--force', action='store_true', help='Force re-replication even if cdn_image_url is set')

    def handle(self, *args, **options):
        limit = options.get('limit')
        product_id = options.get('product_id')
        brand_slug = options.get('brand_slug')
        force = options.get('force')

        qs = AffiliateProduct.objects.filter(is_active=True).exclude(image_url='')
        if product_id:
            qs = qs.filter(id=product_id)
        if brand_slug:
            qs = qs.filter(brand_ref__slug=brand_slug)
        if not force:
            qs = qs.filter(Q(cdn_image_url='') | Q(cdn_image_url__isnull=True))

        total_to_process = qs.count()
        products = list(qs[:limit])

        self.stdout.write(f"Starting image CDN replication for {len(products)} of {total_to_process} products...")

        success_count = 0
        error_count = 0

        for p in products:
            try:
                cdn_url = fetch_and_replicate_image(p)
                if cdn_url:
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"Error on product {p.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Image replication complete. Success: {success_count}, Failed/Skipped: {error_count}"
        ))
