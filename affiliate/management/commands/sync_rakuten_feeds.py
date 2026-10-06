"""
sync_rakuten_feeds.py
Syncs products from Rakuten Advertising (Twinset, D1 Milano, Tory Burch EU)
into AffiliateProduct table. API returns XML.
Features:
- Currency enforcement (strict EUR allowlist)
- Zero-delta guard and 2-run miss-count grace period
- Content hashing (0 DB column churn on unchanged products)
- CatalogSyncRun tracking
- No hard cascading deletes during routine sync
- Auto-refreshes OAuth token safely
"""
import base64
import decimal
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from django.db.models import Q

from affiliate.models import AffiliateProduct, Brand, CatalogSyncRun
from affiliate.ingest import (
    normalize_category,
    normalize_gender,
    normalize_color,
    compute_content_hash,
    flush_catalog_batch,
    apply_stale_deactivation_guard,
)

RAKUTEN_API = 'https://api.linksynergy.com'
ACTIVE_MIDS = [
    {'mid': 53269, 'brand': 'Twinset'},
    {'mid': 47344, 'brand': 'D1 Milano'},
    {'mid': 43656, 'brand': 'Tory Burch EU'},
]


class Command(BaseCommand):
    help = 'Sync products from Rakuten Advertising (Twinset, D1 Milano, Tory Burch EU) with safety guards'

    def add_arguments(self, parser):
        parser.add_argument('--mid', type=int, default=None, help='Sync single advertiser by MID')
        parser.add_argument('--limit', type=int, default=None, help='Max products to import (testing)')
        parser.add_argument('--page-size', type=int, default=100, help='Products per API page (max 100)')
        parser.add_argument('--purge-stale', action='store_true', help='Admin action: purge products inactive >30 days')

    def handle(self, *args, **options):
        if options.get('purge_stale'):
            self._purge_stale_inactive_products()
            return

        self.token = getattr(settings, 'RAKUTEN_TOKEN', None)
        self.sid = getattr(settings, 'RAKUTEN_PUBLISHER_SID', '4674442')
        self.client_id = getattr(settings, 'RAKUTEN_CLIENT_ID', None)
        self.client_secret = getattr(settings, 'RAKUTEN_CLIENT_SECRET', None)
        self.refresh_tok = getattr(settings, 'RAKUTEN_REFRESH_TOKEN', None)
        self.limit = options.get('limit')
        self.page_size = min(options.get('page_size', 100), 100)
        self.total = 0
        self.d1_cache = {}

        bot_ua = getattr(settings, 'MYC_BOT_USER_AGENT', 'CloslyBot/1.0 (+https://myclosly.com/bot)')
        self.http_session = requests.Session()
        self.http_session.headers.update({'User-Agent': bot_ua})

        if not self.token:
            msg = 'RAKUTEN_TOKEN is not set in environment settings. Ingestion halted.'
            self.stdout.write(self.style.ERROR(msg))
            CatalogSyncRun.objects.create(
                feed_id='rakuten_all',
                source=AffiliateProduct.SOURCE_RAKUTEN,
                status=CatalogSyncRun.STATUS_FAILED,
                notes=msg,
                finished_at=timezone.now(),
            )
            raise CommandError(msg)

        single_mid = options.get('mid')
        mids = [m for m in ACTIVE_MIDS if m['mid'] == single_mid] if single_mid else ACTIVE_MIDS

        # Pre-cache or create Brand records for active advertisers
        self.brand_cache = {}
        for adv in mids:
            brand_name = adv['brand']
            brand_obj, _ = Brand.objects.get_or_create(
                slug=re.sub(r'[^a-z0-9]+', '-', brand_name.lower()).strip('-'),
                defaults={
                    'name': brand_name,
                    'kind': Brand.KIND_RAKUTEN,
                    'status': Brand.STATUS_ACTIVE,
                    'external_id': str(adv['mid']),
                    'default_currency': 'EUR',
                },
            )
            self.brand_cache[brand_name.lower()] = brand_obj

        overall_errors = 0
        for adv in mids:
            if self.limit and self.total >= self.limit:
                break
            try:
                self._sync_advertiser(adv['mid'], adv['brand'])
            except Exception as e:
                overall_errors += 1
                self.stdout.write(self.style.ERROR(f"Error syncing {adv['brand']}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f'\nRakuten sync finished. Total imported/processed: {self.total}'
        ))

        if overall_errors > 0:
            raise CommandError(f"Rakuten sync encountered errors in {overall_errors} advertiser feed(s).")

    # ------------------------------------------------------------------ #
    def _sync_advertiser(self, mid: int, brand_name: str):
        self.stdout.write(f'\nSyncing {brand_name} (MID {mid})...')
        sync_time = timezone.now()
        feed_id = f'rakuten_{mid}'

        # Count active products before sync for zero-delta safety calculation
        active_before = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_RAKUTEN,
            aw_product_id__startswith=f'rakuten_{mid}_',
            is_active=True,
        ).count()

        sync_run = CatalogSyncRun.objects.create(
            feed_id=feed_id,
            source=AffiliateProduct.SOURCE_RAKUTEN,
            status=CatalogSyncRun.STATUS_RUNNING,
            started_at=sync_time,
        )

        allowed_currencies = getattr(settings, 'MYC_INGEST_CURRENCIES', ['EUR'])
        page = 1
        brand_rows_seen = 0
        brand_rows_new = 0
        brand_rows_changed = 0
        skipped_currency = 0
        error_count = 0
        completed_full_walk = False

        batch_rows = []
        BATCH_SIZE = 250

        try:
            while True:
                if self.limit and self.total >= self.limit:
                    break

                items, total_pages = self._fetch_page(mid, page)
                if items is None:
                    error_count += 1
                    break

                if not items:
                    completed_full_walk = True
                    break

                for item in items:
                    try:
                        def t(tag):
                            return (item.findtext(tag) or '').strip()

                        item_mid = t('mid') or str(mid)
                        linkid = t('linkid')
                        product_name = t('productname')
                        link_url = t('linkurl')

                        if not product_name or not link_url or not linkid:
                            continue

                        # Strict currency check
                        currency = (t('currency') or '').strip().upper()
                        if not currency or currency not in allowed_currencies:
                            skipped_currency += 1
                            continue

                        network_id = f'rakuten_{item_mid}_{linkid}'

                        sale_str = t('saleprice') or '0'
                        base_str = t('price') or '0'
                        try:
                            sale_price = decimal.Decimal(sale_str.replace(',', '.'))
                        except (decimal.InvalidOperation, ValueError):
                            sale_price = decimal.Decimal('0.00')
                        try:
                            base_price = decimal.Decimal(base_str.replace(',', '.'))
                        except (decimal.InvalidOperation, ValueError):
                            base_price = decimal.Decimal('0.00')

                        if sale_price > 0:
                            price = sale_price
                            rrp = base_price if base_price > sale_price else None
                        else:
                            price = base_price
                            rrp = None

                        image_url = t('imageurl') or t('largeimage') or t('smallimage') or ''
                        merchant_brand = t('merchantname') or brand_name
                        description = t('description') or ''
                        category = t('categoryname') or ''

                        real_merchant_url = ''
                        if link_url and 'murl=' in link_url:
                            try:
                                parsed = urllib.parse.urlparse(link_url)
                                qs = urllib.parse.parse_qs(parsed.query)
                                if 'murl' in qs and qs['murl']:
                                    real_merchant_url = qs['murl'][0]
                            except Exception:
                                pass
                        merchant_deep_link = real_merchant_url or t('clickurl') or t('buyurl') or link_url
                        colour = t('color') or t('colour') or ''

                        additional_images = self._enrich_additional_images(
                            mid=mid,
                            image_url=image_url,
                            link_url=link_url,
                            merchant_deep_link=merchant_deep_link,
                            item=item,
                            brand=merchant_brand,
                        )

                        is_active = bool(price > 0 and image_url)
                        cat_norm = normalize_category(category, product_name)
                        gender_norm = normalize_gender(category, product_name, merchant_brand)
                        color_norm = normalize_color(colour, product_name)
                        chash = compute_content_hash(
                            name=product_name,
                            price=price,
                            rrp_price=rrp,
                            brand=merchant_brand,
                            image_url=image_url,
                            is_active=is_active,
                            currency=currency,
                        )

                        row_dict = {
                            'aw_product_id': network_id,
                            'name': product_name,
                            'brand': merchant_brand,
                            'description': description,
                            'price': price,
                            'rrp_price': rrp,
                            'currency': currency,
                            'image_url': image_url,
                            'additional_image_urls': additional_images,
                            'aw_deep_link': link_url,
                            'merchant_deep_link': merchant_deep_link,
                            'category': category,
                            'category_norm': cat_norm,
                            'gender': gender_norm,
                            'colour': colour,
                            'color_primary': color_norm,
                            'advertiser_name': merchant_brand,
                            'is_active': is_active,
                            'in_stock': is_active,
                            'content_hash': chash,
                        }
                        batch_rows.append(row_dict)
                        brand_rows_seen += 1

                        if len(batch_rows) >= BATCH_SIZE:
                            counts = flush_catalog_batch(
                                rows=batch_rows,
                                sync_time=sync_time,
                                source=AffiliateProduct.SOURCE_RAKUTEN,
                                brand_cache=self.brand_cache,
                            )
                            brand_rows_new += counts['new']
                            brand_rows_changed += counts['changed']
                            batch_rows = []

                    except Exception as row_err:
                        error_count += 1
                        self.stdout.write(self.style.ERROR(f'  Row error: {row_err}'))

                self.stdout.write(f'  Page {page}/{total_pages}: {len(items)} fetched.')

                if total_pages and page >= total_pages:
                    completed_full_walk = True
                    break
                page += 1
                time.sleep(0.25)

            # Flush any remaining batch rows
            if batch_rows:
                counts = flush_catalog_batch(
                    rows=batch_rows,
                    sync_time=sync_time,
                    source=AffiliateProduct.SOURCE_RAKUTEN,
                    brand_cache=self.brand_cache,
                )
                brand_rows_new += counts['new']
                brand_rows_changed += counts['changed']

            self.total += brand_rows_seen

            sync_run.rows_seen = brand_rows_seen
            sync_run.rows_new = brand_rows_new
            sync_run.rows_changed = brand_rows_changed
            sync_run.error_count = error_count

            # Stale product deactivation guard
            # Only apply stale handling if we completed a FULL walk of all pages without --limit
            if completed_full_walk and not self.limit:
                deactivated = apply_stale_deactivation_guard(
                    sync_run=sync_run,
                    active_before=active_before,
                    source=AffiliateProduct.SOURCE_RAKUTEN,
                    sync_time=sync_time,
                    extra_filter={'aw_product_id__startswith': f'rakuten_{mid}_'},
                )
                sync_run.rows_deactivated = deactivated
                if sync_run.status != CatalogSyncRun.STATUS_GUARDED:
                    sync_run.status = CatalogSyncRun.STATUS_SUCCESS
            else:
                if self.limit:
                    sync_run.notes = f"Partial test sync (--limit {self.limit}). Stale deactivation skipped."
                else:
                    sync_run.notes = "Incomplete page walk. Stale deactivation skipped for safety."
                sync_run.status = CatalogSyncRun.STATUS_SUCCESS if error_count == 0 else CatalogSyncRun.STATUS_FAILED

            sync_run.finished_at = timezone.now()
            sync_run.save()

            self.stdout.write(self.style.SUCCESS(
                f"  {brand_name}: seen={brand_rows_seen}, new={brand_rows_new}, "
                f"changed={brand_rows_changed}, skipped_currency={skipped_currency}, "
                f"deactivated={sync_run.rows_deactivated}, status={sync_run.status}"
            ))

        except Exception as e:
            sync_run.status = CatalogSyncRun.STATUS_FAILED
            sync_run.notes = f"Advertiser sync error: {e}"
            sync_run.finished_at = timezone.now()
            sync_run.save()
            self.stdout.write(self.style.ERROR(f"  Error syncing {brand_name}: {e}"))
            raise

    # ------------------------------------------------------------------ #
    def _fetch_page(self, mid: int, page: int):
        """Fetch one page of products. Returns (items_list, total_pages)."""
        url = f'{RAKUTEN_API}/productsearch/1.0'
        params = {'mid': mid, 'pagenumber': page, 'pagesize': self.page_size}

        try:
            resp = self._get(url, params=params)
            if resp is None:
                return None, 0

            root = ET.fromstring(resp.text)
            total_pages = int(root.findtext('TotalPages') or 0)
            items = root.findall('item')
            return items, total_pages

        except ET.ParseError as e:
            self.stdout.write(self.style.ERROR(f'  XML parse error page {page}: {e}'))
            return None, 0
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Error fetching page {page}: {e}'))
            return None, 0

    # ------------------------------------------------------------------ #
    def _enrich_additional_images(self, mid, image_url, link_url, merchant_deep_link, item, brand=''):
        """Enrich additional_images for Rakuten merchants with single-image feeds."""
        additional = []

        # 1. XML tags
        for img_tag in ('largeimage', 'smallimage', 'alternateimage'):
            val = (item.findtext(img_tag) or '').strip()
            if val and val.startswith(('http://', 'https://')) and val != image_url and val not in additional:
                additional.append(val)

        if not image_url:
            return additional

        # 2. D1 Milano (MID 47344)
        if '47344' in str(mid) or 'd1milano' in (link_url or '').lower() or 'd1milano' in (merchant_deep_link or '').lower():
            handle = None
            for u in (merchant_deep_link, link_url):
                unquoted = urllib.parse.unquote(u or '')
                m = re.search(r'd1milano\.com/products/([a-zA-Z0-9\-_]+)', unquoted)
                if m:
                    handle = m.group(1)
                    break
            if handle:
                if handle not in self.d1_cache:
                    try:
                        resp = self.http_session.get(f'https://d1milano.com/products/{handle}.json', timeout=4)
                        if resp.status_code == 200:
                            data = resp.json()
                            imgs = [img['src'] for img in data.get('product', {}).get('images', []) if img.get('src')]
                            self.d1_cache[handle] = imgs
                        else:
                            self.d1_cache[handle] = []
                    except Exception:
                        self.d1_cache[handle] = []
                for img_src in self.d1_cache.get(handle, []):
                    clean_src = img_src.split('?')[0] if '?' in img_src else img_src
                    clean_main = image_url.split('?')[0] if '?' in image_url else image_url
                    if clean_src != clean_main and img_src not in additional:
                        additional.append(img_src)

        # 3. Tory Burch EU (MID 43656)
        if '43656' in str(mid) or 'tory burch' in (brand or '').lower() or 'toryburch' in (link_url or '').lower():
            if '_SLANG' in image_url:
                for view in ('SLSID', 'SLDET', 'SLTOP', 'SLBOT', 'SLBAC', 'SLFRO'):
                    extra = re.sub(r'_SLANG(\.[^\s?]+|\?[^\s]*)', f'_{view}\\1', image_url)
                    if extra != image_url and extra not in additional:
                        additional.append(extra)
            elif '_SLSID' in image_url:
                for view in ('SLANG', 'SLDET', 'SLTOP', 'SLBOT', 'SLBAC', 'SLFRO'):
                    extra = re.sub(r'_SLSID(\.[^\s?]+|\?[^\s]*)', f'_{view}\\1', image_url)
                    if extra != image_url and extra not in additional:
                        additional.append(extra)

        return additional

    # ------------------------------------------------------------------ #
    def _get(self, url, params=None):
        resp = self.http_session.get(
            url,
            headers={'Authorization': f'Bearer {self.token}'},
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            self.stdout.write('  Token expired — refreshing...')
            if self._refresh_token():
                resp = self.http_session.get(
                    url,
                    headers={'Authorization': f'Bearer {self.token}'},
                    params=params,
                    timeout=30,
                )
            else:
                self.stdout.write(self.style.ERROR('  Could not refresh token.'))
                return None

        if resp.status_code != 200:
            self.stdout.write(self.style.ERROR(f'  HTTP {resp.status_code}: {resp.text[:200]}'))
            return None

        return resp

    def _refresh_token(self):
        """Get a new access token using client credentials."""
        if not self.client_id or not self.client_secret:
            return False
        try:
            token_key = base64.b64encode(
                f'{self.client_id}:{self.client_secret}'.encode()
            ).decode()

            r = self.http_session.post(
                f'{RAKUTEN_API}/token',
                headers={
                    'Authorization': f'Bearer {token_key}',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                data=f'scope={self.sid}',
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                self.token = data['access_token']
                self.refresh_tok = data.get('refresh_token', self.refresh_tok)
                self.stdout.write('  Token refreshed successfully.')
                return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Token refresh error: {e}'))
        return False

    def _purge_stale_inactive_products(self):
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        stale_qs = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_RAKUTEN,
            is_active=False,
            updated_at__lt=cutoff,
            # Protect items with active user relations
            clicks__isnull=True,
            favorited_by__isnull=True,
        )
        purged, _ = stale_qs.delete()
        self.stdout.write(self.style.SUCCESS(f'Safely purged {purged} abandoned inactive Rakuten products.'))
