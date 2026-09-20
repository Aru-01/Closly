"""
sync_rakuten_feeds.py
Syncs products from Rakuten Advertising (Twinset, D1 Milano, Tory Burch EU)
into AffiliateProduct table. API returns XML.
Auto-refreshes the OAuth token when expired.
"""
import base64
import decimal
import time
import xml.etree.ElementTree as ET
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from affiliate.models import AffiliateProduct

RAKUTEN_API  = 'https://api.linksynergy.com'
ACTIVE_MIDS  = [
    {'mid': 53269, 'brand': 'Twinset'},
    {'mid': 47344, 'brand': 'D1 Milano'},
    {'mid': 43656, 'brand': 'Tory Burch EU'},
]


class Command(BaseCommand):
    help = 'Sync products from Rakuten Advertising (Twinset, D1 Milano, Tory Burch EU)'

    def add_arguments(self, parser):
        parser.add_argument('--mid',      type=int,  default=None, help='Sync single advertiser by MID')
        parser.add_argument('--limit',    type=int,  default=None, help='Max products to import (testing)')
        parser.add_argument('--page-size',type=int,  default=100,  help='Products per API page (max 100)')

    def handle(self, *args, **options):
        self.token      = getattr(settings, 'RAKUTEN_TOKEN', None)
        self.sid        = getattr(settings, 'RAKUTEN_PUBLISHER_SID', '4674442')
        self.client_id  = getattr(settings, 'RAKUTEN_CLIENT_ID', None)
        self.client_secret = getattr(settings, 'RAKUTEN_CLIENT_SECRET', None)
        self.refresh_tok = getattr(settings, 'RAKUTEN_REFRESH_TOKEN', None)
        self.limit      = options.get('limit')
        self.page_size  = min(options.get('page_size', 100), 100)
        self.total      = 0

        if not self.token:
            self.stdout.write(self.style.ERROR('RAKUTEN_TOKEN not set in .env'))
            return

        single_mid = options.get('mid')
        mids = [m for m in ACTIVE_MIDS if m['mid'] == single_mid] if single_mid else ACTIVE_MIDS

        for adv in mids:
            if self.limit and self.total >= self.limit:
                break
            self._sync_advertiser(adv['mid'], adv['brand'])

        # Auto-purge inactive Rakuten products older than 30 days
        from datetime import timedelta
        cutoff = self._now() - timedelta(days=30)
        purged, _ = AffiliateProduct.objects.filter(
            source=AffiliateProduct.SOURCE_RAKUTEN,
            is_active=False,
            updated_at__lt=cutoff
        ).delete()
        if purged:
            self.stdout.write(self.style.NOTICE(f'Purged {purged} inactive Rakuten products older than 30 days.'))

        self.stdout.write(self.style.SUCCESS(
            f'\nRakuten sync complete. Total imported/updated: {self.total}'
        ))
        self._cleanup_test_file()

    # ------------------------------------------------------------------ #
    def _sync_advertiser(self, mid, brand_name):
        self.stdout.write(f'\nSyncing {brand_name} (MID {mid})...')
        sync_time   = self._now()
        page        = 1
        brand_total = 0

        while True:
            if self.limit and self.total >= self.limit:
                break

            items, total_pages = self._fetch_page(mid, page)
            if not items:
                break

            saved = self._save_products(items, sync_time)
            brand_total  += saved
            self.total   += saved
            self.stdout.write(f'  Page {page}/{total_pages}: {len(items)} fetched, {saved} saved')

            if page >= total_pages:
                break
            page += 1
            time.sleep(0.25)

        self.stdout.write(self.style.SUCCESS(f'  {brand_name}: {brand_total} products synced.'))

    # ------------------------------------------------------------------ #
    def _fetch_page(self, mid, page):
        """Fetch one page of products. Returns (items_list, total_pages)."""
        url = f'{RAKUTEN_API}/productsearch/1.0'
        params = {'mid': mid, 'pagenumber': page, 'pagesize': self.page_size}

        try:
            resp = self._get(url, params=params)
            if resp is None:
                return [], 0

            # Parse XML
            root = ET.fromstring(resp.text)
            total_pages = int(root.findtext('TotalPages') or 0)
            items = root.findall('item')
            return items, total_pages

        except ET.ParseError as e:
            self.stdout.write(self.style.ERROR(f'  XML parse error page {page}: {e}'))
            return [], 0
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Error fetching page {page}: {e}'))
            return [], 0

    # ------------------------------------------------------------------ #
    def _save_products(self, items, sync_time):
        deduped = {}
        for item in items:
            try:
                def t(tag):
                    return (item.findtext(tag) or '').strip()

                mid          = t('mid')
                linkid       = t('linkid')
                product_name = t('productname')
                link_url     = t('linkurl')      # affiliate tracking URL

                if not product_name or not link_url:
                    continue

                # Unique ID: rakuten_<mid>_<linkid>
                network_id = f'rakuten_{mid}_{linkid}'

                sale_str  = t('saleprice') or '0'
                base_str  = t('price') or '0'
                try:
                    sale_price = decimal.Decimal(sale_str.replace(',', '.'))
                except decimal.InvalidOperation:
                    sale_price = decimal.Decimal('0.00')
                try:
                    base_price = decimal.Decimal(base_str.replace(',', '.'))
                except decimal.InvalidOperation:
                    base_price = decimal.Decimal('0.00')

                if sale_price > 0:
                    price = sale_price
                    rrp   = base_price if base_price > sale_price else None
                else:
                    price = base_price
                    rrp   = None

                currency = t('currency') or 'GBP'
                image_url = t('imageurl') or t('largeimage') or t('smallimage') or ''
                brand = t('merchantname') or ''
                description = t('description') or ''
                category = t('categoryname') or ''
                merchant_deep_link = t('clickurl') or t('buyurl') or link_url
                colour = t('color') or t('colour') or ''

                deduped[network_id] = AffiliateProduct(
                    aw_product_id=network_id,
                    source=AffiliateProduct.SOURCE_RAKUTEN,
                    name=product_name,
                    brand=brand,
                    description=description,
                    price=price,
                    rrp_price=rrp if rrp and rrp != price else None,
                    currency=currency,
                    image_url=image_url,
                    aw_deep_link=link_url,
                    merchant_deep_link=merchant_deep_link,
                    category=category,
                    advertiser_name=brand,
                    colour=colour,
                    is_active=True,
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Row error: {e}'))

        if deduped:
            AffiliateProduct.objects.bulk_create(
                list(deduped.values()),
                update_conflicts=True,
                unique_fields=['aw_product_id'],
                update_fields=[
                    'source', 'name', 'brand', 'description', 'price',
                    'rrp_price', 'currency', 'image_url', 'aw_deep_link',
                    'merchant_deep_link', 'category', 'advertiser_name',
                    'colour', 'is_active', 'updated_at',
                ],
            )
        return len(deduped)

    # ------------------------------------------------------------------ #
    # HTTP helper with auto token refresh
    # ------------------------------------------------------------------ #
    def _get(self, url, params=None):
        resp = requests.get(
            url,
            headers={'Authorization': f'Bearer {self.token}'},
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            self.stdout.write('  Token expired — refreshing...')
            if self._refresh_token():
                resp = requests.get(
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

            r = requests.post(
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
                self.stdout.write(f'  Token refreshed successfully.')
                # Update settings in memory (not .env — that requires manual update)
                settings.RAKUTEN_TOKEN = self.token
                return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Token refresh error: {e}'))
        return False

    def _now(self):
        from django.utils import timezone
        return timezone.now()

    def _cleanup_test_file(self):
        import os
        test_file = 'rakuten_test.py'
        if os.path.exists(test_file):
            os.remove(test_file)
