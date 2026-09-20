import csv
import gzip
import decimal
import io
import random
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from affiliate.models import AffiliateProduct


class Command(BaseCommand):
    help = 'Sync product feeds from Awin affiliate network (gzip CSV)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mock',
            action='store_true',
            help='Generate mock fashion products instead of calling Awin API',
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
            help='Permanently delete products that have been inactive (is_active=False) for >30 days',
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
            self.stdout.write(self.style.ERROR(
                'AWIN_FEED_URL is not set. Add it to your .env file.'
            ))
            self.stdout.write(self.style.WARNING('Falling back to mock data...'))
            self.generate_mock_data()
            return

        if csv_path:
            self.stdout.write(f'Reading from local file: {csv_path}')
            self._sync_from_local(csv_path, limit)
        else:
            self.stdout.write(f'Fetching Awin feed (gzip CSV)...')
            self._sync_from_url(feed_url, limit)

    # ------------------------------------------------------------------
    # Sync from remote URL (gzip compressed CSV)
    # ------------------------------------------------------------------
    def _sync_from_url(self, feed_url, limit):
        try:
            self.stdout.write('Downloading feed... (this may take a minute for large feeds)')
            response = requests.get(feed_url, timeout=180)
            response.raise_for_status()

            # Decompress gzip in memory
            compressed = io.BytesIO(response.content)
            with gzip.GzipFile(fileobj=compressed) as f:
                text = io.TextIOWrapper(f, encoding='utf-8', errors='replace')
                self._parse_and_import(text, limit)

        except requests.exceptions.Timeout:
            self.stdout.write(self.style.ERROR('Request timed out. The feed is large — try again or use --local-csv.'))
        except requests.exceptions.HTTPError as e:
            self.stdout.write(self.style.ERROR(f'HTTP error fetching feed: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch/decompress feed: {e}'))

    # ------------------------------------------------------------------
    # Sync from local file (plain CSV or .gz)
    # ------------------------------------------------------------------
    def _sync_from_local(self, csv_path, limit):
        try:
            if csv_path.endswith('.gz'):
                with gzip.open(csv_path, 'rt', encoding='utf-8', errors='replace') as f:
                    self._parse_and_import(f, limit)
            else:
                with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                    self._parse_and_import(f, limit)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File not found: {csv_path}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to read local file: {e}'))

    # ------------------------------------------------------------------
    # Core parse & import logic
    # ------------------------------------------------------------------
    def _parse_and_import(self, file_obj, limit=None):
        from django.utils import timezone as tz
        reader = csv.DictReader(file_obj)

        if not reader.fieldnames:
            self.stdout.write(self.style.ERROR('CSV has no headers — cannot parse.'))
            return

        self.stdout.write(f'CSV columns detected: {", ".join(reader.fieldnames[:10])}...')

        # Awin column name mapping
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

        # Use a sync timestamp to identify stale products without storing all IDs
        sync_time = tz.now()

        success_count = 0
        skip_count = 0
        error_count = 0

        BATCH_SIZE = 1000
        batch = []

        def flush_batch(rows):
            if not rows:
                return
            # Deduplicate by aw_product_id within batch to prevent PostgreSQL CardinalityViolation
            deduped = {}
            for r in rows:
                deduped[r['aw_product_id']] = r

            instances = [
                AffiliateProduct(
                    aw_product_id=r['aw_product_id'],
                    source=AffiliateProduct.SOURCE_AWIN,
                    name=r['name'],
                    brand=r['brand'],
                    description=r['description'],
                    price=r['price'],
                    rrp_price=r['rrp_price'],
                    currency=r['currency'],
                    image_url=r['image_url'],
                    aw_deep_link=r['aw_deep_link'],
                    merchant_deep_link=r['merchant_deep_link'],
                    category=r['category'],
                    advertiser_name=r['advertiser_name'],
                    colour=r['colour'],
                    is_active=r['is_active'],
                )
                for r in deduped.values()
            ]
            AffiliateProduct.objects.bulk_create(
                instances,
                update_conflicts=True,
                unique_fields=['aw_product_id'],
                update_fields=[
                    'source', 'name', 'brand', 'description', 'price',
                    'rrp_price', 'currency', 'image_url', 'aw_deep_link',
                    'merchant_deep_link', 'category', 'advertiser_name',
                    'colour', 'is_active', 'updated_at',
                ],
            )

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

                brand      = (row.get(COL['brand'], '') or row.get(COL['advertiser'], 'Unknown')).strip()
                description = row.get(COL['description'], '').strip()
                currency    = row.get(COL['currency'], 'GBP').strip() or 'GBP'
                category    = row.get(COL['category'], '').strip()
                advertiser  = row.get(COL['advertiser'], '').strip()
                colour      = row.get(COL['colour'], '').strip()
                merchant_deep_link = row.get(COL['merchant_deep_link'], '').strip()

                image_url = (
                    row.get(COL['large_image'], '').strip()
                    or row.get(COL['image_url'], '').strip()
                    or row.get('merchant_image_url', '').strip()
                )

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
                is_active = in_stock_val not in ('0', 'false', 'no', 'out of stock', '')

                batch.append({
                    'aw_product_id':      aw_product_id,
                    'name':               name,
                    'brand':              brand,
                    'description':        description,
                    'price':              price,
                    'rrp_price':          rrp_price,
                    'currency':           currency,
                    'image_url':          image_url,
                    'aw_deep_link':       aw_deep_link,
                    'merchant_deep_link': merchant_deep_link,
                    'category':           category,
                    'advertiser_name':    advertiser,
                    'colour':             colour,
                    'is_active':          is_active,
                    'updated_at':         sync_time,
                })
                success_count += 1

                if len(batch) >= BATCH_SIZE:
                    flush_batch(batch)
                    batch = []
                    if success_count % 1000 == 0:
                        self.stdout.write(f'  Imported {success_count} products so far...')

            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    self.stdout.write(self.style.ERROR(f'Row error: {e}'))

        # Flush remaining rows
        if batch:
            flush_batch(batch)

        # Deactivate products NOT seen in this sync using the timestamp.
        # This avoids the SQLite 999-variable limit entirely.
        deactivated = 0
        purged = 0
        if not limit:  # Only deactivate & purge on full sync, not limited test runs
            deactivated = AffiliateProduct.objects.filter(
                source=AffiliateProduct.SOURCE_AWIN,
                is_active=True,
                updated_at__lt=sync_time,
            ).update(is_active=False)

            # Auto-purge inactive products older than 30 days
            purged = self._purge_stale_inactive_products(source=AffiliateProduct.SOURCE_AWIN)

        self.stdout.write(self.style.SUCCESS(
            f'\nSync complete!\n'
            f'  Imported/Updated  : {success_count}\n'
            f'  Skipped (bad data): {skip_count}\n'
            f'  Errors             : {error_count}\n'
            f'  Deactivated (gone) : {deactivated}\n'
            f'  Purged (>30d dead) : {purged}'
        ))

    def _purge_stale_inactive_products(self, source=None):
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        qs = AffiliateProduct.objects.filter(is_active=False, updated_at__lt=cutoff)
        if source:
            qs = qs.filter(source=source)
        count, _ = qs.delete()
        self.stdout.write(self.style.NOTICE(f'Purged {count} inactive products older than 30 days.'))
        return count

    # ------------------------------------------------------------------
    # Mock data generator for local testing without Awin
    # ------------------------------------------------------------------
    def generate_mock_data(self):
        self.stdout.write('Generating mock fashion affiliate products...')

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
                currency='GBP',
                image_url=images[category],
                aw_deep_link=f'https://www.awin1.com/cread.php?awinmid=99999&awinaffid=2612792&ued=https://www.{brand_slug}.com/product/{i}',
                merchant_deep_link=f'https://www.{brand_slug}.com/product/{i}',
                category=category,
                advertiser_name=f'{brand} Official',
                colour=random.choice(['Black', 'White', 'Navy', 'Beige', 'Red', 'Green']),
                is_active=True,
            ))

        AffiliateProduct.objects.bulk_create(
            mock_instances,
            update_conflicts=True,
            unique_fields=['aw_product_id'],
            update_fields=[
                'source', 'name', 'brand', 'description', 'price', 'rrp_price',
                'currency', 'image_url', 'aw_deep_link', 'merchant_deep_link',
                'category', 'advertiser_name', 'colour', 'is_active', 'updated_at',
            ],
        )
        count = len(mock_instances)

        self.stdout.write(self.style.SUCCESS(f'Generated {count} mock products successfully.'))
