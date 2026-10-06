import csv
import gzip
import decimal
import io
import random
import requests
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone

from affiliate.models import AffiliateProduct, Brand, CatalogSyncRun
from affiliate.ingest import (
    normalize_category,
    normalize_gender,
    normalize_color,
    compute_content_hash,
    flush_catalog_batch,
    apply_stale_deactivation_guard,
)


class Command(BaseCommand):
    help = 'Sync product feeds from Awin affiliate network with zero-delta safety, content hash, and EUR enforcement'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mock',
            action='store_true',
            help='Explicitly generate mock fashion products (only for local test/dev)',
        )
        parser.add_argument(
            '--local-csv',
            type=str,
            help='Path to a local (optionally gzipped) CSV file instead of fetching from URL',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of products to import (useful for testing)',
        )
        parser.add_argument(
            '--purge-stale',
            action='store_true',
            help='Admin action: purge products that have been inactive for >30 days',
        )

    def handle(self, *args, **options):
        if options.get('purge_stale'):
            self._purge_stale_inactive_products()
            return

        self.stdout.write(self.style.WARNING('Starting Awin affiliate products sync...'))

        if options['mock']:
            self.generate_mock_data()
            return

        csv_path = options.get('local_csv')
        limit = options.get('limit')
        feed_url = getattr(settings, 'AWIN_FEED_URL', None)

        if not csv_path and not feed_url:
            msg = 'AWIN_FEED_URL is not set in environment settings. Ingestion halted.'
            self.stdout.write(self.style.ERROR(msg))
            # Production safety: NEVER silently insert mock catalogue data without --mock
            CatalogSyncRun.objects.create(
                feed_id='awin_feed',
                source=AffiliateProduct.SOURCE_AWIN,
                status=CatalogSyncRun.STATUS_FAILED,
                notes=msg,
                finished_at=timezone.now(),
            )
            raise CommandError(msg)

        if csv_path:
            self.stdout.write(f'Reading from local file: {csv_path}')
            self._sync_from_local(csv_path, limit)
        else:
            self.stdout.write('Streaming Awin feed (gzip CSV)...')
            self._sync_from_url(feed_url, limit)

    def _sync_from_url(self, feed_url, limit):
        sync_run = CatalogSyncRun.objects.create(
            feed_id='awin_feed',
            source=AffiliateProduct.SOURCE_AWIN,
            status=CatalogSyncRun.STATUS_RUNNING,
        )
        try:
            self.stdout.write('Connecting to feed stream...')
            # Memory safety: stream gzip stream directly into decompressor without loading full payload in memory
            response = requests.get(feed_url, stream=True, timeout=180)
            response.raise_for_status()

            response.raw.decode_content = True
            with gzip.GzipFile(fileobj=response.raw) as gz:
                text_stream = io.TextIOWrapper(gz, encoding='utf-8', errors='replace')
                self._parse_and_import(text_stream, limit, sync_run)

        except Exception as e:
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = f"Feed download/processing error: {e}"
            sync_run.finished_at = timezone.now()
            sync_run.save(update_fields=['status', 'notes', 'finished_at'])
            self.stdout.write(self.style.ERROR(f'Failed Awin sync: {e}'))
            raise

    def _sync_from_local(self, csv_path, limit):
        sync_run = CatalogSyncRun.objects.create(
            feed_id=f'awin_local_{csv_path}',
            source=AffiliateProduct.SOURCE_AWIN,
            status=CatalogSyncRun.STATUS_RUNNING,
        )
        try:
            if csv_path.endswith('.gz'):
                with gzip.open(csv_path, 'rt', encoding='utf-8', errors='replace') as f:
                    self._parse_and_import(f, limit, sync_run)
            else:
                with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                    self._parse_and_import(f, limit, sync_run)
        except Exception as e:
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = f"Local file read error: {e}"
            sync_run.finished_at = timezone.now()
            sync_run.save(update_fields=['status', 'notes', 'finished_at'])
            self.stdout.write(self.style.ERROR(f'Failed local Awin sync: {e}'))
            raise

    def _parse_and_import(self, file_obj, limit, sync_run):
        sync_time = timezone.now()
        allowed_currencies = getattr(settings, 'MYC_INGEST_CURRENCIES', ['EUR'])

        active_before = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_AWIN,
            is_active=True,
        ).count()

        reader = csv.DictReader(file_obj)
        if not reader.fieldnames:
            msg = 'CSV has no headers — cannot parse.'
            self.stdout.write(self.style.ERROR(msg))
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = msg
            sync_run.finished_at = timezone.now()
            sync_run.save(update_fields=['status', 'notes', 'finished_at'])
            return

        # Warm brand cache
        brand_cache = {b.name.strip().lower(): b for b in Brand.objects.all()}

        COL = {
            'aw_product_id':      'aw_product_id',
            'name':               'product_name',
            'brand':              'brand_name',
            'description':        'description',
            'price':              'search_price',
            'currency':           'currency',
            'image_url':          'aw_image_url',
            'aw_deep_link':       'aw_deep_link',
            'category':           'category_name',
            'advertiser':         'merchant_name',
            'in_stock':           'in_stock',
            'colour':             'colour',
            'large_image':        'large_image',
            'rrp_price':          'rrp_price',
            'merchant_deep_link': 'merchant_deep_link',
        }

        success_count = 0
        skip_count = 0
        error_count = 0
        total_new = 0
        total_changed = 0
        total_unchanged = 0

        BATCH_SIZE = 1000
        batch = []

        for row in reader:
            if limit and success_count >= limit:
                break

            try:
                aw_product_id = row.get(COL['aw_product_id'], '').strip()
                name          = row.get(COL['name'], '').strip()
                aw_deep_link  = row.get(COL['aw_deep_link'], '').strip()

                if not aw_product_id or not name or not aw_deep_link:
                    skip_count += 1
                    continue

                # EUR/DACH Market enforcement: reject non-EUR currency
                currency = (row.get(COL['currency']) or '').strip().upper()
                if not currency or currency not in allowed_currencies:
                    skip_count += 1
                    continue

                brand = (row.get(COL['brand'], '') or row.get(COL['advertiser'], 'Unknown')).strip()
                description = row.get(COL['description'], '').strip()
                raw_category = row.get(COL['category'], '').strip()
                advertiser = row.get(COL['advertiser'], '').strip()
                colour = row.get(COL['colour'], '').strip()
                merchant_deep_link = row.get(COL['merchant_deep_link'], '').strip()

                image_url = (
                    row.get(COL['large_image'], '').strip()
                    or row.get(COL['image_url'], '').strip()
                    or row.get('merchant_image_url', '').strip()
                )

                additional_images = []
                for extra_col in ('alternate_image', 'alternate_image_two', 'alternate_image_three', 'alternate_image_four', 'more_images'):
                    val = row.get(extra_col, '').strip()
                    if val and val.startswith(('http://', 'https://')) and val not in additional_images and val != image_url:
                        additional_images.append(val)

                price_str = row.get(COL['price'], '0').strip()
                try:
                    price = decimal.Decimal(price_str) if price_str else decimal.Decimal('0.00')
                except decimal.InvalidOperation:
                    price = decimal.Decimal('0.00')

                rrp_str = row.get(COL['rrp_price'], '').strip()
                try:
                    rrp_price = decimal.Decimal(rrp_str) if rrp_str else None
                except decimal.InvalidOperation:
                    rrp_price = None

                in_stock_val = row.get(COL['in_stock'], '1').strip().lower()
                in_stock = in_stock_val not in ('0', 'false', 'no', 'out of stock', '')
                is_active = in_stock and price > 0

                # Normalization
                category_norm = normalize_category(raw_category, name)
                gender = normalize_gender(raw_category, name, brand)
                color_primary = normalize_color(colour, name)

                chash = compute_content_hash(
                    name=name,
                    price=price,
                    rrp_price=rrp_price,
                    brand=brand,
                    image_url=image_url,
                    is_active=is_active,
                    currency=currency,
                )

                batch.append({
                    'aw_product_id': aw_product_id,
                    'name': name,
                    'brand': brand,
                    'description': description,
                    'price': price,
                    'rrp_price': rrp_price,
                    'currency': currency,
                    'image_url': image_url,
                    'additional_image_urls': additional_images,
                    'aw_deep_link': aw_deep_link,
                    'merchant_deep_link': merchant_deep_link,
                    'category': raw_category,
                    'category_norm': category_norm,
                    'gender': gender,
                    'colour': colour,
                    'color_primary': color_primary,
                    'advertiser_name': advertiser,
                    'is_active': is_active,
                    'in_stock': in_stock,
                    'content_hash': chash,
                })
                success_count += 1

                if len(batch) >= BATCH_SIZE:
                    stats = flush_catalog_batch(batch, sync_time, AffiliateProduct.SOURCE_AWIN, brand_cache)
                    total_new += stats['new']
                    total_changed += stats['changed']
                    total_unchanged += stats['unchanged']
                    batch = []

            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    self.stdout.write(self.style.ERROR(f'Row error: {e}'))

        if batch:
            stats = flush_catalog_batch(batch, sync_time, AffiliateProduct.SOURCE_AWIN, brand_cache)
            total_new += stats['new']
            total_changed += stats['changed']
            total_unchanged += stats['unchanged']

        sync_run.rows_seen = success_count
        sync_run.rows_new = total_new
        sync_run.rows_changed = total_changed
        sync_run.rows_unchanged = total_unchanged
        sync_run.error_count = error_count

        deactivated = 0
        if not limit:
            deactivated = apply_stale_deactivation_guard(
                sync_run=sync_run,
                active_before=active_before,
                source=AffiliateProduct.SOURCE_AWIN,
                sync_time=sync_time,
            )

        sync_run.rows_deactivated = deactivated
        if sync_run.status == CatalogSyncRun.STATUS_RUNNING:
            sync_run.status = CatalogSyncRun.STATUS_SUCCESS

        sync_run.finished_at = timezone.now()
        sync_run.save()

        self.stdout.write(self.style.SUCCESS(
            f'\nAwin Sync complete!\n'
            f'  Status             : {sync_run.status}\n'
            f'  Rows seen          : {success_count}\n'
            f'  New products       : {total_new}\n'
            f'  Changed products   : {total_changed}\n'
            f'  Unchanged products : {total_unchanged}\n'
            f'  Deactivated        : {deactivated}\n'
            f'  Skipped (bad/non-EUR): {skip_count}\n'
            f'  Errors             : {error_count}'
        ))

    def _purge_stale_inactive_products(self):
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        qs = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_AWIN,
            is_active=False,
            updated_at__lt=cutoff
        )
        count, _ = qs.delete()
        self.stdout.write(self.style.NOTICE(f'Purged {count} inactive Awin products older than 30 days.'))
        return count

    def generate_mock_data(self):
        self.stdout.write('Generating mock fashion affiliate products (explicit --mock)...')

        brands = ['Zara', 'H&M', 'Nike', 'Adidas', 'Mango', 'ASOS', "Levi's", 'Puma', 'New Look', 'River Island']
        categories = [
            'Clothing & Accessories > Dresses',
            'Clothing & Accessories > Tops',
            'Clothing & Accessories > Jackets & Coats',
            'Clothing & Accessories > Trousers & Jeans',
            'Clothing & Accessories > Shoes & Boots',
            'Clothing & Accessories > Bags & Accessories',
        ]
        items = {
            'Clothing & Accessories > Dresses': ['Floral Midi Dress', 'Evening Wrap Dress', 'Linen Sundress'],
            'Clothing & Accessories > Tops': ['Ribbed Knit Top', 'Satin Camisole', 'Oversized Graphic Tee'],
            'Clothing & Accessories > Jackets & Coats': ['Denim Jacket', 'Wool Trench Coat', 'Bomber Jacket'],
            'Clothing & Accessories > Trousers & Jeans': ['Slim-Fit Jeans', 'Wide Leg Trousers', 'Cargo Pants'],
            'Clothing & Accessories > Shoes & Boots': ['Leather Chelsea Boots', 'Canvas Sneakers', 'Strappy Heels'],
            'Clothing & Accessories > Bags & Accessories': ['Leather Crossbody', 'Canvas Tote', 'Mini Backpack'],
        }
        images = {
            'Clothing & Accessories > Dresses': 'https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=800&fit=crop',
            'Clothing & Accessories > Tops': 'https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?w=800&fit=crop',
            'Clothing & Accessories > Jackets & Coats': 'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&fit=crop',
            'Clothing & Accessories > Trousers & Jeans': 'https://images.unsplash.com/photo-1542272604-787c3835535d?w=800&fit=crop',
            'Clothing & Accessories > Shoes & Boots': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&fit=crop',
            'Clothing & Accessories > Bags & Accessories': 'https://images.unsplash.com/photo-1584917865442-de89df76afd3?w=800&fit=crop',
        }

        mock_instances = []
        sync_time = timezone.now()

        for i in range(1, 101):
            category = random.choice(categories)
            brand = random.choice(brands)
            item = random.choice(items[category])
            name = f'{brand} {item}'
            price = decimal.Decimal(f'{random.uniform(19.99, 249.99):.2f}')
            rrp   = price + decimal.Decimal(f'{random.uniform(5, 50):.2f}')
            brand_slug = brand.lower().replace("'", '').replace(' ', '')

            mock_instances.append(AffiliateProduct(
                aw_product_id=f'mock_{i:06d}',
                source=AffiliateProduct.SOURCE_AWIN,
                name=name,
                brand=brand,
                description=f'Discover the {name}. A perfect blend of style and comfort, ideal for any occasion.',
                price=price,
                rrp_price=rrp,
                currency='EUR',
                gender=normalize_gender(category, name, brand),
                category=category,
                category_norm=normalize_category(category, name),
                image_url=images[category],
                aw_deep_link=f'https://www.awin1.com/cread.php?awinmid=99999&awinaffid=2612792&ued=https://www.{brand_slug}.com/product/{i}',
                merchant_deep_link=f'https://www.{brand_slug}.com/product/{i}',
                advertiser_name=f'{brand} Official',
                colour=random.choice(['Black', 'White', 'Navy', 'Beige', 'Red', 'Green']),
                color_primary=normalize_color('', name),
                is_active=True,
                in_stock=True,
                first_seen_at=sync_time,
                last_seen_at=sync_time,
            ))

        AffiliateProduct.objects.bulk_create(
            mock_instances,
            update_conflicts=True,
            unique_fields=['aw_product_id'],
            update_fields=[
                'source', 'name', 'brand', 'description', 'price', 'rrp_price',
                'currency', 'image_url', 'aw_deep_link', 'merchant_deep_link',
                'category', 'category_norm', 'gender', 'advertiser_name', 'colour',
                'color_primary', 'is_active', 'in_stock', 'updated_at',
            ],
        )
        count = len(mock_instances)
        self.stdout.write(self.style.SUCCESS(f'Generated {count} mock products successfully.'))
