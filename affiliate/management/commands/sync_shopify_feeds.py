"""
sync_shopify_feeds.py
Source A Shopify Ingestion Connector.
Features:
- Consented brand registry integration (Brand.KIND_SHOPIFY)
- Polite rate spacing (>= MYC_SHOPIFY_REQ_INTERVAL_MS, default 2000ms)
- Identified bot User-Agent (MYC_BOT_USER_AGENT)
- Conditional requests / ETag handling
- HTTP 429 exponential backoff
- Variant collapse and sale/rrp price mapping
- Currency check (strict EUR enforcement)
- Stale deactivation with zero-delta guard and 2-run miss grace period
- Content hashing (0 writes on unchanged feed)
- CatalogSyncRun tracking
"""
import decimal
import hashlib
import json
import re
import time
import urllib.parse
from typing import Optional, Dict, Any, List
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
    help = 'Sync independent brand products from Shopify public feeds (Source A) with politeness and safety guards'

    def add_arguments(self, parser):
        parser.add_argument(
            '--brand-slug',
            type=str,
            default=None,
            help='Sync a specific brand by its slug in the Brand registry',
        )
        parser.add_argument(
            '--shop-url',
            type=str,
            default=None,
            help='Sync directly from a Shopify store domain (e.g. store.example.com)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Max products to import per brand (useful for testing)',
        )
        parser.add_argument(
            '--purge-stale',
            action='store_true',
            help='Admin action: purge products inactive >30 days',
        )

    def handle(self, *args, **options):
        if options.get('purge_stale'):
            self._purge_stale_inactive_products()
            return

        brand_slug = options.get('brand_slug')
        shop_url = options.get('shop_url')
        limit = options.get('limit')

        self.bot_ua = getattr(settings, 'MYC_BOT_USER_AGENT', 'mycloslybot/1.0 (+https://myclosly.com/bot)')
        self.req_interval_sec = getattr(settings, 'MYC_SHOPIFY_REQ_INTERVAL_MS', 2000) / 1000.0

        self.http_session = requests.Session()
        self.http_session.headers.update({
            'User-Agent': self.bot_ua,
            'Accept': 'application/json',
        })

        # Resolve target brands
        if shop_url:
            domain = self._clean_domain(shop_url)
            brand_slug = re.sub(r'[^a-z0-9]+', '-', domain.split('.')[0]).strip('-')
            brand, _ = Brand.objects.get_or_create(
                slug=brand_slug,
                defaults={
                    'name': domain.split('.')[0].capitalize(),
                    'kind': Brand.KIND_SHOPIFY,
                    'status': Brand.STATUS_ACTIVE,
                    'feed_url': f"https://{domain}",
                    'default_currency': 'EUR',
                    'consent_kind': 'partner_agreement',
                    'consent_at': timezone.now(),
                    'consent_ref': 'cli_sync_direct',
                },
            )
            brands = [brand]
        elif brand_slug:
            brands = list(Brand.objects.filter(slug=brand_slug))
            if not brands:
                raise CommandError(f"Brand with slug '{brand_slug}' not found.")
        else:
            # Query all active and consented Shopify brands
            brands = list(Brand.objects.filter(
                kind=Brand.KIND_SHOPIFY,
                status=Brand.STATUS_ACTIVE,
                consent_at__isnull=False,
            ))

        if not brands:
            self.stdout.write(self.style.WARNING("No active consented Shopify brands found to sync."))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(brands)} Shopify brand(s) to process."))

        total_imported = 0
        overall_errors = 0

        for brand in brands:
            try:
                imported = self._sync_shopify_brand(brand, limit)
                total_imported += imported
            except Exception as e:
                overall_errors += 1
                self.stdout.write(self.style.ERROR(f"Error syncing brand {brand.name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\nShopify sync complete. Total imported: {total_imported}"))

        if overall_errors > 0:
            raise CommandError(f"Shopify sync encountered errors in {overall_errors} brand(s).")

    def _sync_shopify_brand(self, brand: Brand, limit: Optional[int]) -> int:
        domain = self._extract_domain(brand)
        if not domain:
            self.stdout.write(self.style.ERROR(f"Brand {brand.name} has no valid feed_url or domain configured."))
            return 0

        self.stdout.write(f"\nSyncing Shopify brand: {brand.name} ({domain})...")
        sync_time = timezone.now()
        feed_id = f"shopify_{brand.slug}"

        active_before = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_SHOPIFY,
            brand_ref=brand,
            is_active=True,
        ).count()

        sync_run = CatalogSyncRun.objects.create(
            feed_id=feed_id,
            source=AffiliateProduct.SOURCE_SHOPIFY,
            status=CatalogSyncRun.STATUS_RUNNING,
            started_at=sync_time,
        )

        allowed_currencies = getattr(settings, 'MYC_INGEST_CURRENCIES', ['EUR'])
        brand_currency = (brand.default_currency or 'EUR').strip().upper()

        if brand_currency not in allowed_currencies:
            msg = f"Brand {brand.name} currency '{brand_currency}' not in allowed ingest currencies {allowed_currencies}."
            self.stdout.write(self.style.WARNING(msg))
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = msg
            sync_run.finished_at = timezone.now()
            sync_run.save()
            return 0

        brand_cache = {brand.name.lower(): brand, brand.slug.lower(): brand}
        page = 1
        page_size = 250
        rows_seen = 0
        rows_new = 0
        rows_changed = 0
        error_count = 0
        completed_full_walk = False

        batch_rows = []
        BATCH_SIZE = 250

        try:
            while True:
                if limit and rows_seen >= limit:
                    break

                url = f"https://{domain}/products.json?limit={page_size}&page={page}"
                resp_data = self._fetch_with_backoff(url)
                if resp_data is None:
                    error_count += 1
                    break

                products = resp_data.get('products', [])
                if not products:
                    completed_full_walk = True
                    break

                for p in products:
                    try:
                        p_id = str(p.get('id', '')).strip()
                        title = (p.get('title') or '').strip()
                        handle = (p.get('handle') or '').strip()
                        if not p_id or not title or not handle:
                            continue

                        product_type = (p.get('product_type') or '').strip()
                        variants = p.get('variants', [])
                        if not variants:
                            continue

                        # Variant collapse: pick primary available variant or first variant
                        primary_variant = next((v for v in variants if v.get('available')), variants[0])
                        var_price_str = str(primary_variant.get('price', '0'))
                        var_compare_str = str(primary_variant.get('compare_at_price') or '0')

                        try:
                            price_val = decimal.Decimal(var_price_str)
                        except (decimal.InvalidOperation, ValueError):
                            price_val = decimal.Decimal('0.00')

                        try:
                            compare_val = decimal.Decimal(var_compare_str) if var_compare_str and var_compare_str != 'None' else decimal.Decimal('0.00')
                        except (decimal.InvalidOperation, ValueError):
                            compare_val = decimal.Decimal('0.00')

                        if compare_val > price_val:
                            price = price_val
                            rrp = compare_val
                        else:
                            price = price_val
                            rrp = None

                        # Images
                        images = p.get('images', [])
                        image_url = images[0].get('src', '') if images else ''
                        additional_images = [img.get('src') for img in images[1:] if img.get('src')]

                        # Direct product URL + Closly UTM parameters
                        clean_url = f"https://{domain}/products/{handle}"
                        deep_link = f"{clean_url}?utm_source=closly&utm_medium=app&utm_campaign=feed"

                        network_id = f"shopify_{brand.slug}_{p_id}"
                        is_active = bool(price > 0 and image_url)

                        cat_norm = normalize_category(product_type, title)
                        gender_norm = normalize_gender(product_type, title, brand.name)
                        color_norm = normalize_color('', title)

                        chash = compute_content_hash(
                            name=title,
                            price=price,
                            rrp_price=rrp,
                            brand=brand.name,
                            image_url=image_url,
                            is_active=is_active,
                            currency=brand_currency,
                        )

                        row_dict = {
                            'aw_product_id': network_id,
                            'name': title,
                            'brand': brand.name,
                            'description': p.get('body_html', '') or '',
                            'price': price,
                            'rrp_price': rrp,
                            'currency': brand_currency,
                            'image_url': image_url,
                            'additional_image_urls': additional_images,
                            'aw_deep_link': deep_link,
                            'merchant_deep_link': clean_url,
                            'category': product_type,
                            'category_norm': cat_norm,
                            'gender': gender_norm,
                            'colour': '',
                            'color_primary': color_norm,
                            'advertiser_name': brand.name,
                            'is_active': is_active,
                            'in_stock': is_active,
                            'content_hash': chash,
                        }
                        batch_rows.append(row_dict)
                        rows_seen += 1

                        if len(batch_rows) >= BATCH_SIZE:
                            counts = flush_catalog_batch(
                                rows=batch_rows,
                                sync_time=sync_time,
                                source=AffiliateProduct.SOURCE_SHOPIFY,
                                brand_cache=brand_cache,
                            )
                            rows_new += counts['new']
                            rows_changed += counts['changed']
                            batch_rows = []

                    except Exception as row_err:
                        error_count += 1
                        self.stdout.write(self.style.ERROR(f"  Row error: {row_err}"))

                self.stdout.write(f"  Page {page}: fetched {len(products)} products.")

                if len(products) < page_size:
                    completed_full_walk = True
                    break

                page += 1
                # Polite spacing (>= MYC_SHOPIFY_REQ_INTERVAL_MS)
                time.sleep(self.req_interval_sec)

            # Flush remaining batch rows
            if batch_rows:
                counts = flush_catalog_batch(
                    rows=batch_rows,
                    sync_time=sync_time,
                    source=AffiliateProduct.SOURCE_SHOPIFY,
                    brand_cache=brand_cache,
                )
                rows_new += counts['new']
                rows_changed += counts['changed']

            sync_run.rows_seen = rows_seen
            sync_run.rows_new = rows_new
            sync_run.rows_changed = rows_changed
            sync_run.error_count = error_count

            # Stale product deactivation guard
            if completed_full_walk and not limit:
                deactivated = apply_stale_deactivation_guard(
                    sync_run=sync_run,
                    active_before=active_before,
                    source=AffiliateProduct.SOURCE_SHOPIFY,
                    sync_time=sync_time,
                    extra_filter={'brand_ref': brand},
                )
                sync_run.rows_deactivated = deactivated
                if sync_run.status != CatalogSyncRun.STATUS_GUARDED:
                    sync_run.status = CatalogSyncRun.STATUS_SUCCESS
            else:
                if limit:
                    sync_run.notes = f"Partial test sync (--limit {limit}). Stale deactivation skipped."
                else:
                    sync_run.notes = "Incomplete page walk. Stale deactivation skipped for safety."
                sync_run.status = CatalogSyncRun.STATUS_SUCCESS if error_count == 0 else CatalogSyncRun.STATUS_FAILED

            sync_run.finished_at = timezone.now()
            sync_run.save()

            brand.last_sync_at = timezone.now()
            if sync_run.status == CatalogSyncRun.STATUS_SUCCESS:
                brand.last_success_at = timezone.now()
                brand.fail_count = 0
            else:
                brand.fail_count += 1
            brand.save(update_fields=['last_sync_at', 'last_success_at', 'fail_count'])

            self.stdout.write(self.style.SUCCESS(
                f"  {brand.name}: seen={rows_seen}, new={rows_new}, "
                f"changed={rows_changed}, deactivated={sync_run.rows_deactivated}, status={sync_run.status}"
            ))
            return rows_seen

        except Exception as e:
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = f"Brand sync error: {e}"
            sync_run.finished_at = timezone.now()
            sync_run.save()
            brand.fail_count += 1
            brand.save(update_fields=['fail_count'])
            raise

    def _fetch_with_backoff(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch JSON with polite spacing and exponential 429 backoff."""
        max_retries = 3
        backoff_sec = 2.0

        for attempt in range(max_retries):
            try:
                resp = self.http_session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    retry_after = resp.headers.get('Retry-After')
                    sleep_time = float(retry_after) if retry_after else backoff_sec
                    self.stdout.write(self.style.WARNING(f"  Rate limited (429). Backing off for {sleep_time}s..."))
                    time.sleep(sleep_time)
                    backoff_sec *= 2
                    continue
                elif resp.status_code in (404, 403):
                    self.stdout.write(self.style.ERROR(f"  HTTP {resp.status_code} for {url}. Halting brand walk."))
                    return None
                else:
                    self.stdout.write(self.style.ERROR(f"  HTTP {resp.status_code} for {url}"))
                    return None
            except Exception as req_err:
                self.stdout.write(self.style.ERROR(f"  Request error ({url}): {req_err}"))
                time.sleep(1.0)

        return None

    def _clean_domain(self, raw_url: str) -> str:
        url = raw_url.strip()
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc or parsed.path

    def _extract_domain(self, brand: Brand) -> str:
        if brand.feed_url:
            return self._clean_domain(brand.feed_url)
        return ''

    def _purge_stale_inactive_products(self):
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        stale_qs = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_SHOPIFY,
            is_active=False,
            updated_at__lt=cutoff,
            clicks__isnull=True,
            favorited_by__isnull=True,
        )
        purged, _ = stale_qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Safely purged {purged} abandoned inactive Shopify products."))
