from django.core.management.base import BaseCommand
from django.utils.text import slugify
from affiliate.models import AffiliateProduct, Brand


class Command(BaseCommand):
    help = 'Backfill Brand registry entities from existing AffiliateProduct brand text and link brand_ref'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Number of brands to process in one transaction batch',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting Brand backfill and brand_ref linking...'))

        distinct_brands = list(
            AffiliateProduct.objects.exclude(brand='').order_by().values_list('brand', flat=True).distinct()
        )
        self.stdout.write(f'Found {len(distinct_brands)} distinct brand strings.')

        created_count = 0
        linked_count = 0

        existing_brands = {b.name.strip().lower(): b for b in Brand.objects.all()}

        for brand_name in distinct_brands:
            clean_name = brand_name.strip()
            if not clean_name:
                continue

            key = clean_name.lower()
            if key in existing_brands:
                brand_obj = existing_brands[key]
            else:
                base_slug = slugify(clean_name) or 'brand'
                slug = base_slug[:240]
                counter = 1
                while Brand.objects.filter(slug=slug).exists():
                    slug = f"{base_slug[:230]}-{counter}"
                    counter += 1

                brand_obj = Brand.objects.create(
                    name=clean_name,
                    slug=slug,
                    kind=Brand.KIND_AWIN,
                    status=Brand.STATUS_LIVE,
                    tier=Brand.TIER_INDIE,
                    currency='EUR',
                )
                existing_brands[key] = brand_obj
                created_count += 1

            updated = AffiliateProduct.objects.filter(brand=brand_name, brand_ref__isnull=True).update(brand_ref=brand_obj)
            linked_count += updated

        self.stdout.write(self.style.SUCCESS(
            f'Brand backfill complete!\n'
            f'  New Brands created: {created_count}\n'
            f'  Products linked   : {linked_count}'
        ))
