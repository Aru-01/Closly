import decimal
import hashlib
import socket
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from affiliate.models import (
    AffiliateProduct,
    Brand,
    CatalogSyncRun,
    ProductClick,
    ProductFavorite,
    Event,
    FeedImpressionsDaily,
    Conversion,
)
from affiliate.ingest import (
    normalize_category,
    normalize_gender,
    normalize_color,
    compute_content_hash,
    flush_catalog_batch,
    apply_stale_deactivation_guard,
)
from affiliate.views.product_views import build_affiliate_url
from affiliate.services.image_cdn import (
    validate_image_url_safe,
    fetch_and_replicate_image,
    purge_ended_brand_images,
)

User = get_user_model()


class AffiliateCatalogAndNewsfeedTests(APITestCase):
    """
    Tests for Catalogue Newsfeed, Search, Filtering, and Normalized Metadata.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='shopper@example.com',
            password='Password123!',
            name='Shopper User',
        )

        self.brand_zara = Brand.objects.create(name='Zara', slug='zara', status=Brand.STATUS_ACTIVE)
        self.brand_hm = Brand.objects.create(name='H&M', slug='hm', status=Brand.STATUS_ACTIVE)
        self.brand_nike = Brand.objects.create(name='Nike', slug='nike', status=Brand.STATUS_ACTIVE)

        self.product1 = AffiliateProduct.objects.create(
            aw_product_id="test_aw_1",
            brand_ref=self.brand_zara,
            name="Zara Summer Floral Dress",
            brand="Zara",
            description="A beautiful floral dress.",
            price=decimal.Decimal("49.99"),
            rrp_price=decimal.Decimal("99.99"),
            currency="EUR",
            image_url="https://example.com/zara-dress.jpg",
            aw_deep_link="https://awin1.com/zara-dress",
            category="Womenswear > Dresses",
            category_norm="Dresses",
            gender=AffiliateProduct.GENDER_WOMEN,
            colour="Red",
            color_primary="red",
            advertiser_name="Zara Retail",
            is_active=True,
        )

        self.product2 = AffiliateProduct.objects.create(
            aw_product_id="test_aw_2",
            brand_ref=self.brand_hm,
            name="H&M Oxford Shirt",
            brand="H&M",
            description="Classic button-down shirt.",
            price=decimal.Decimal("29.99"),
            rrp_price=decimal.Decimal("39.99"),
            currency="EUR",
            image_url="https://example.com/hm-shirt.jpg",
            aw_deep_link="https://awin1.com/hm-shirt",
            category="Menswear > Shirts",
            category_norm="Shirts",
            gender=AffiliateProduct.GENDER_MEN,
            colour="Blue",
            color_primary="blue",
            advertiser_name="H&M Retail",
            is_active=True,
        )

        self.inactive_product = AffiliateProduct.objects.create(
            aw_product_id="test_aw_3",
            brand_ref=self.brand_nike,
            name="Nike Inactive Sneakers",
            brand="Nike",
            description="Comfortable running sneakers.",
            price=decimal.Decimal("89.99"),
            currency="EUR",
            image_url="https://example.com/nike-sneakers.jpg",
            aw_deep_link="https://awin1.com/nike-sneakers",
            category="Footwear > Sneakers",
            category_norm="Shoes",
            advertiser_name="Nike Retail",
            is_active=False,
        )

    def test_get_newsfeed_products(self):
        """Test retrieving all active EUR affiliate products from newsfeed."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        # Only active EUR products should be returned (2 active, 1 inactive)
        self.assertEqual(len(response.data['data']['results']), 2)
        self.assertEqual(response.data['data']['count'], 2)

    def test_filter_by_brand(self):
        """Test filtering products in the newsfeed by brand."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url, {'brand': 'Zara'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['results']), 1)
        self.assertEqual(response.data['data']['results'][0]['brand'], 'Zara')

    def test_search_products(self):
        """Test searching in the newsfeed."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url, {'search': 'Oxford'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['results']), 1)
        self.assertEqual(response.data['data']['results'][0]['name'], 'H&M Oxford Shirt')

    def test_discount_ordering(self):
        """Regression test for CF-23: ordering=discount must sort by discount percentage descending."""
        # Zara: (99.99 - 49.99) / 99.99 = 50.00%
        # H&M:  (39.99 - 29.99) / 39.99 = 25.00%
        url = reverse('affiliate:products-feed')
        response = self.client.get(url, {'ordering': 'discount'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['data']['results']
        self.assertEqual(len(results), 2)
        # Zara has 50% discount and must be first, H&M second
        self.assertEqual(results[0]['brand'], 'Zara')
        self.assertEqual(results[1]['brand'], 'H&M')

    def test_get_brands_list(self):
        """Test fetching unique active brands."""
        url = reverse('affiliate:brands-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        brand_names = [b['brand'] for b in response.data['data']['brands']]
        self.assertIn('Zara', brand_names)
        self.assertIn('H&M', brand_names)
        self.assertNotIn('Nike', brand_names)


class AffiliateAttributionTests(APITestCase):
    """
    Tests for Click Attribution (AWIN clickref/clickref2, Rakuten u1, UUID uniqueness, throttling, idempotency).
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='clicker@example.com',
            password='Password123!',
            name='Clicker User',
        )
        self.client.force_authenticate(user=self.user)

        self.awin_product = AffiliateProduct.objects.create(
            aw_product_id='awin_attr_1',
            source=AffiliateProduct.SOURCE_AWIN,
            name='Awin Coat',
            brand='CoatBrand',
            price=decimal.Decimal('120.00'),
            currency='EUR',
            image_url='https://example.com/coat.jpg',
            aw_deep_link='https://www.awin1.com/pclick.php?p=123&a=456&m=789',
            is_active=True,
        )

        self.rakuten_product = AffiliateProduct.objects.create(
            aw_product_id='rakuten_attr_2',
            source=AffiliateProduct.SOURCE_RAKUTEN,
            name='Rakuten Watch',
            brand='WatchBrand',
            price=decimal.Decimal('250.00'),
            currency='EUR',
            image_url='https://example.com/watch.jpg',
            aw_deep_link='https://click.linksynergy.com/fs-bin/click?id=XYZ&offerid=1&type=1&subid=0',
            is_active=True,
        )

    def test_awin_clickref_attribution_url(self):
        """Test AWIN outbound URL appends clickref and clickref2 while preserving existing query parameters."""
        click_uuid = uuid.uuid4()
        outbound = build_affiliate_url(self.awin_product, click_ref=click_uuid, surface='for_you')

        self.assertIn(f'clickref={click_uuid.hex}', outbound)
        self.assertIn('clickref2=for_you', outbound)
        self.assertIn('p=123', outbound)
        self.assertIn('a=456', outbound)

    def test_rakuten_u1_attribution_url(self):
        """Test Rakuten outbound URL appends u1 SubID while preserving existing query parameters."""
        click_uuid = uuid.uuid4()
        outbound = build_affiliate_url(self.rakuten_product, click_ref=click_uuid, surface='for_you')

        self.assertIn(f'u1={click_uuid.hex}', outbound)
        self.assertIn('id=XYZ', outbound)

    def test_product_click_endpoint_creates_record(self):
        """Test clicking product creates ProductClick with UUID and returns {click_id, url}."""
        url = reverse('affiliate:product-click', kwargs={'pk': self.awin_product.pk})
        data = {
            'surface': 'for_you',
            'session_id': 'sess_abc123',
        }
        res = self.client.post(url, data=data, HTTP_USER_AGENT='CloslyTestAgent/1.0')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        click_id = res.data['data']['click_id']
        outbound_url = res.data['data']['url']

        # Verify DB record
        click_rec = ProductClick.objects.get(click_ref=click_id)
        self.assertEqual(click_rec.user, self.user)
        self.assertEqual(click_rec.product, self.awin_product)
        self.assertEqual(click_rec.surface, 'for_you')
        self.assertEqual(click_rec.session_id, 'sess_abc123')
        self.assertTrue(click_rec.user_agent_hash)
        self.assertIn(f'clickref={click_rec.click_ref.hex}', outbound_url)
        self.assertIn('clickref2=for_you', outbound_url)

    def test_product_click_idempotency(self):
        """Test sending identical Idempotency-Key returns the existing click_id."""
        url = reverse('affiliate:product-click', kwargs={'pk': self.awin_product.pk})
        headers = {'HTTP_IDEMPOTENCY_KEY': 'idem-key-unique-999'}

        res1 = self.client.post(url, data={'surface': 'for_you'}, **headers)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        click_id1 = res1.data['data']['click_id']

        res2 = self.client.post(url, data={'surface': 'for_you'}, **headers)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        click_id2 = res2.data['data']['click_id']

        self.assertEqual(click_id1, click_id2)
        # Should not create duplicate records in DB
        self.assertEqual(ProductClick.objects.filter(idempotency_key='idem-key-unique-999').count(), 1)

    def test_product_click_throttling_at_thirty_per_hour(self):
        """Test rate limit enforces maximum 30 clicks/hour/user and returns HTTP 429 on the 31st request."""
        url = reverse('affiliate:product-click', kwargs={'pk': self.awin_product.pk})
        # 30 allowed clicks
        for i in range(30):
            res = self.client.post(url, data={'surface': 'for_you'})
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 31st click receives 429 Too Many Requests
        res_throttled = self.client.post(url, data={'surface': 'for_you'})
        self.assertEqual(res_throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class AffiliateIngestionSafetyTests(APITestCase):
    """
    Tests for Ingestion Safety (Currency enforcement, Content hashing, Zero-delta guard, Miss-count grace period).
    """

    def setUp(self):
        cache.clear()
        self.brand = Brand.objects.create(name='TestBrand', slug='testbrand', status=Brand.STATUS_ACTIVE)
        self.brand_cache = {'testbrand': self.brand}

    def test_content_hash_unchanged_sync_causes_zero_writes(self):
        """Test content hash prevents unnecessary writes when product payload is unchanged."""
        sync_time1 = timezone.now() - timedelta(hours=5)
        chash = compute_content_hash(
            name='Silk Scarf',
            price=decimal.Decimal('45.00'),
            rrp_price=None,
            brand='TestBrand',
            image_url='https://example.com/scarf.jpg',
            is_active=True,
            currency='EUR',
        )

        rows = [{
            'aw_product_id': 'ingest_hash_1',
            'name': 'Silk Scarf',
            'brand': 'TestBrand',
            'price': decimal.Decimal('45.00'),
            'rrp_price': None,
            'currency': 'EUR',
            'image_url': 'https://example.com/scarf.jpg',
            'aw_deep_link': 'https://example.com/scarf',
            'is_active': True,
            'content_hash': chash,
        }]

        # 1st sync: creates product
        res1 = flush_catalog_batch(rows, sync_time=sync_time1, source='awin', brand_cache=self.brand_cache)
        self.assertEqual(res1['new'], 1)
        self.assertEqual(res1['changed'], 0)
        self.assertEqual(res1['unchanged'], 0)

        # 2nd sync: identical payload -> 0 new, 0 changed, 1 unchanged
        sync_time2 = timezone.now()
        res2 = flush_catalog_batch(rows, sync_time=sync_time2, source='awin', brand_cache=self.brand_cache)
        self.assertEqual(res2['new'], 0)
        self.assertEqual(res2['changed'], 0)
        self.assertEqual(res2['unchanged'], 1)

    def test_zero_delta_guard_prevents_deactivation(self):
        """Test if rows_seen < 50% of active_before, zero-delta guard halts deactivation and marks GUARDED."""
        sync_time = timezone.now()
        # Seed 10 active products
        for i in range(10):
            AffiliateProduct.objects.create(
                aw_product_id=f'zd_prod_{i}',
                source=AffiliateProduct.SOURCE_AWIN,
                name=f'Product {i}',
                brand='TestBrand',
                price=decimal.Decimal('20.00'),
                currency='EUR',
                image_url='https://example.com/p.jpg',
                is_active=True,
                last_seen_at=sync_time - timedelta(days=1),
            )

        sync_run = CatalogSyncRun.objects.create(
            feed_id='awin_feed',
            source=AffiliateProduct.SOURCE_AWIN,
            status=CatalogSyncRun.STATUS_RUNNING,
            rows_seen=3,  # Only 3 seen, which is 30% (< 50% threshold)
        )

        deactivated = apply_stale_deactivation_guard(
            sync_run=sync_run,
            active_before=10,
            source=AffiliateProduct.SOURCE_AWIN,
            sync_time=sync_time,
        )

        self.assertEqual(deactivated, 0)
        sync_run.refresh_from_db()
        self.assertEqual(sync_run.status, CatalogSyncRun.STATUS_GUARDED)
        # All 10 products must still be active!
        self.assertEqual(AffiliateProduct.objects.filter(source='awin', is_active=True).count(), 10)

    def test_miss_count_two_run_grace_period(self):
        """Test products missing for 1 run remain active; missing for 2 consecutive runs are deactivated."""
        sync_time1 = timezone.now()
        prod = AffiliateProduct.objects.create(
            aw_product_id='grace_prod_1',
            source=AffiliateProduct.SOURCE_AWIN,
            name='Vanishing Top',
            brand='TestBrand',
            price=decimal.Decimal('30.00'),
            currency='EUR',
            image_url='https://example.com/top.jpg',
            is_active=True,
            miss_count=0,
            last_seen_at=sync_time1 - timedelta(hours=10),
        )

        sync_run1 = CatalogSyncRun.objects.create(
            feed_id='awin_feed',
            source=AffiliateProduct.SOURCE_AWIN,
            status=CatalogSyncRun.STATUS_RUNNING,
            rows_seen=100,  # Safe threshold
        )

        # Run 1: product missing
        apply_stale_deactivation_guard(
            sync_run=sync_run1,
            active_before=1,
            source=AffiliateProduct.SOURCE_AWIN,
            sync_time=sync_time1,
        )
        prod.refresh_from_db()
        self.assertEqual(prod.miss_count, 1)
        self.assertTrue(prod.is_active)  # Still active after 1st miss!

        # Run 2: product missing again
        sync_time2 = timezone.now() + timedelta(hours=5)
        sync_run2 = CatalogSyncRun.objects.create(
            feed_id='awin_feed',
            source=AffiliateProduct.SOURCE_AWIN,
            status=CatalogSyncRun.STATUS_RUNNING,
            rows_seen=100,
        )
        apply_stale_deactivation_guard(
            sync_run=sync_run2,
            active_before=1,
            source=AffiliateProduct.SOURCE_AWIN,
            sync_time=sync_time2,
        )
        prod.refresh_from_db()
        self.assertEqual(prod.miss_count, 2)
        self.assertFalse(prod.is_active)  # Deactivated on 2nd miss!


class AffiliateForYouFeedTests(APITestCase):
    """
    Tests for For You Feed (Single candidate pool, brand diversity, saved exclusion, stable pagination).
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='fashionista@example.com',
            password='Password123!',
            name='Fashionista',
            gender='female',
        )
        self.client.force_authenticate(user=self.user)

    def test_saved_product_strictly_excluded_from_for_you(self):
        """Test products favorited/saved by the user are excluded from their For You feed."""
        prod = AffiliateProduct.objects.create(
            aw_product_id='prod_saved_exc',
            name='Chic Trenchcoat',
            brand='Burberry',
            price=decimal.Decimal('450.00'),
            currency='EUR',
            image_url='https://example.com/trench.jpg',
            gender=AffiliateProduct.GENDER_WOMEN,
            is_active=True,
        )

        # 1. Product is visible before saving
        url = reverse('affiliate:products-for-you')
        res1 = self.client.get(url, {'seed': 12345})
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        p_ids1 = [p['id'] for p in res1.data['data']['results']]
        self.assertIn(prod.id, p_ids1)

        # 2. Save/favorite the product
        ProductFavorite.objects.create(product=prod, user=self.user)
        cache.clear()

        # 3. Product must now be excluded from For You feed
        res2 = self.client.get(url, {'seed': 12345})
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        p_ids2 = [p['id'] for p in res2.data['data']['results']]
        self.assertNotIn(prod.id, p_ids2)

    def test_single_candidate_pool_supports_more_than_eight_brands(self):
        """Test candidate pool is not starved to only 8 brands (CF-03)."""
        # Create products across 12 distinct brands
        for b_idx in range(12):
            brand_name = f'DesignerBrand_{b_idx}'
            AffiliateProduct.objects.create(
                aw_product_id=f'cand_b_{b_idx}',
                name=f'{brand_name} Signature Piece',
                brand=brand_name,
                price=decimal.Decimal('99.00'),
                currency='EUR',
                image_url=f'https://example.com/b_{b_idx}.jpg',
                gender=AffiliateProduct.GENDER_WOMEN,
                is_active=True,
            )

        url = reverse('affiliate:products-for-you')
        res = self.client.get(url, {'page_size': 20, 'seed': 54321})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data['data']['results']
        brands_seen = {p['brand'] for p in results}
        # In the old code, max 8 brands could ever exist in the pool.
        # Now, all 12 brands should be represented in the candidates!
        self.assertGreater(len(brands_seen), 8)

    def test_brand_diversity_in_twenty_window(self):
        """Test greedy diversity caps any brand at max 3 items in a 20-product window."""
        # Create 10 items for 'DominantBrand' and 15 items for 'OtherBrand'
        for i in range(10):
            AffiliateProduct.objects.create(
                aw_product_id=f'dom_{i}',
                name=f'Dominant Item {i}',
                brand='DominantBrand',
                price=decimal.Decimal('50.00'),
                currency='EUR',
                image_url=f'https://example.com/dom_{i}.jpg',
                gender=AffiliateProduct.GENDER_WOMEN,
                is_active=True,
            )
        for j in range(25):
            AffiliateProduct.objects.create(
                aw_product_id=f'other_{j}',
                name=f'Other Brand Item {j}',
                brand=f'Diverse_{j}',
                price=decimal.Decimal('50.00'),
                currency='EUR',
                image_url=f'https://example.com/other_{j}.jpg',
                gender=AffiliateProduct.GENDER_WOMEN,
                is_active=True,
            )

        url = reverse('affiliate:products-for-you')
        res = self.client.get(url, {'page': 1, 'page_size': 20, 'seed': 77777})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data['data']['results']

        dom_count = sum(1 for p in results if p['brand'] == 'DominantBrand')
        self.assertLessEqual(dom_count, 3)

    def test_stable_pagination_zero_overlap(self):
        """Test pagination across pages 1 and 2 with the same seed has 0 duplicate products."""
        for i in range(30):
            AffiliateProduct.objects.create(
                aw_product_id=f'page_item_{i}',
                name=f'Essential Style {i}',
                brand=f'Brand_{i % 6}',
                price=decimal.Decimal('40.00') + i,
                currency='EUR',
                image_url=f'https://example.com/item_{i}.jpg',
                gender=AffiliateProduct.GENDER_WOMEN,
                is_active=True,
            )

        url = reverse('affiliate:products-for-you')
        res_p1 = self.client.get(url, {'page': 1, 'page_size': 10, 'seed': 88888})
        res_p2 = self.client.get(url, {'page': 2, 'page_size': 10, 'seed': 88888})

        self.assertEqual(res_p1.status_code, status.HTTP_200_OK)
        self.assertEqual(res_p2.status_code, status.HTTP_200_OK)

        ids_p1 = [p['id'] for p in res_p1.data['data']['results']]
        ids_p2 = [p['id'] for p in res_p2.data['data']['results']]

        self.assertEqual(len(ids_p1), 10)
        self.assertEqual(len(ids_p2), 10)
        overlap = set(ids_p1).intersection(set(ids_p2))
        self.assertEqual(len(overlap), 0)


class AffiliateUserBehaviorEventsTests(APITestCase):
    """
    Tests for User Behavior Events Batch API (/api/affiliate/events/batch/).
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='eventer@example.com',
            password='Password123!',
            name='Event User',
        )
        self.client.force_authenticate(user=self.user)

        self.product = AffiliateProduct.objects.create(
            aw_product_id='evt_prod_1',
            name='Event Test Dress',
            brand='FashionCo',
            price=decimal.Decimal('75.00'),
            currency='EUR',
            image_url='https://example.com/dress.jpg',
            is_active=True,
        )

    def test_events_batch_successful_ingestion(self):
        """Test submitting valid batch of discovery events."""
        url = reverse('affiliate:events-batch')
        payload = {
            'events': [
                {
                    'event_type': 'impression',
                    'product_id': self.product.id,
                    'source': 'for_you',
                    'feed_page': 1,
                    'dwell_ms': 500,
                },
                {
                    'event_type': 'detail_view',
                    'product_id': self.product.id,
                    'source': 'for_you',
                    'feed_page': 1,
                    'dwell_ms': 3200,
                },
                {
                    'event_type': 'like',
                    'product_id': self.product.id,
                    'source': 'for_you',
                }
            ]
        }
        res = self.client.post(url, data=payload, format='json')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['data']['ingested_count'], 3)
        self.assertEqual(Event.objects.filter(user=self.user).count(), 3)

    def test_events_batch_daily_impression_deduplication(self):
        """Test duplicate impression on the same page/product on the same day is deduplicated."""
        url = reverse('affiliate:events-batch')
        payload = {
            'events': [
                {
                    'event_type': 'impression',
                    'product_id': self.product.id,
                    'source': 'for_you',
                    'feed_page': 1,
                    'dwell_ms': 400,
                },
                {
                    'event_type': 'impression',
                    'product_id': self.product.id,
                    'source': 'for_you',
                    'feed_page': 1,
                    'dwell_ms': 600,
                },
            ]
        }
        res = self.client.post(url, data=payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # Should deduplicate in-batch and record only 1 impression
        self.assertEqual(Event.objects.filter(user=self.user, event_type='impression').count(), 1)

    def test_events_batch_max_size_enforcement(self):
        """Test batches exceeding 200 events are rejected."""
        url = reverse('affiliate:events-batch')
        payload = {
            'events': [
                {
                    'event_type': 'impression',
                    'product_id': self.product.id,
                }
                for _ in range(201)
            ]
        }
        res = self.client.post(url, data=payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data['success'])


class AffiliateFavoritesTests(APITestCase):
    """
    Tests for Favorites (Race-condition safety, explicit save/remove action, PUT/DELETE methods).
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='lover@example.com',
            password='Password123!',
            name='Lover User',
        )
        self.client.force_authenticate(user=self.user)

        self.product = AffiliateProduct.objects.create(
            aw_product_id='fav_prod_1',
            name='Love Coat',
            brand='WarmBrand',
            price=decimal.Decimal('150.00'),
            currency='EUR',
            image_url='https://example.com/coat.jpg',
            is_active=True,
        )

    def test_favorite_toggle_and_explicit_actions(self):
        """Test atomic toggle, explicit action='save', and explicit action='remove'."""
        url = reverse('affiliate:product-love', kwargs={'pk': self.product.pk})

        # 1. Explicit save action
        res_save = self.client.post(url, data={'action': 'save'}, format='json')
        self.assertEqual(res_save.status_code, status.HTTP_200_OK)
        self.assertTrue(res_save.data['data']['is_loved'])
        self.assertEqual(ProductFavorite.objects.filter(product=self.product, user=self.user).count(), 1)

        # 2. Idempotent save action (repeat)
        res_save2 = self.client.post(url, data={'action': 'save'}, format='json')
        self.assertEqual(res_save2.status_code, status.HTTP_200_OK)
        self.assertTrue(res_save2.data['data']['is_loved'])
        self.assertEqual(ProductFavorite.objects.filter(product=self.product, user=self.user).count(), 1)

        # 3. Explicit remove action
        res_remove = self.client.post(url, data={'action': 'remove'}, format='json')
        self.assertEqual(res_remove.status_code, status.HTTP_200_OK)
        self.assertFalse(res_remove.data['data']['is_loved'])
        self.assertEqual(ProductFavorite.objects.filter(product=self.product, user=self.user).count(), 0)

        # 4. HTTP DELETE method
        # First save it
        self.client.post(url, data={'action': 'save'}, format='json')
        res_delete = self.client.delete(url)
        self.assertEqual(res_delete.status_code, status.HTTP_200_OK)
        self.assertFalse(res_delete.data['data']['is_loved'])
        self.assertEqual(ProductFavorite.objects.filter(product=self.product, user=self.user).count(), 0)


class AffiliateImageCDNTests(APITestCase):
    """
    Tests for Audit Item CF-18:
    - URL safety & SSRF guards (loopback, private ranges, metadata, schemes)
    - Image fetching, SHA-256 hashing, storage replication, deduplication
    - Serializer preference for CDN URL
    - AWIN Brand-ended image purge
    """

    def setUp(self):
        cache.clear()
        self.brand = Brand.objects.create(name='Acme Fashion', slug='acme-fashion', status=Brand.STATUS_ACTIVE)
        self.product = AffiliateProduct.objects.create(
            aw_product_id='cdn_prod_1',
            brand_ref=self.brand,
            name='Acme Silk Shirt',
            brand='Acme Fashion',
            price=decimal.Decimal('79.99'),
            currency='GBP',
            image_url='https://images.example.com/products/shirt.jpg',
            is_active=True,
        )

    def test_ssrf_guard_blocks_dangerous_urls(self):
        """SSRF Guard must block localhost, private IPs, loopback, and metadata endpoints."""
        # Non-http/https
        self.assertFalse(validate_image_url_safe('ftp://example.com/img.jpg'))
        self.assertFalse(validate_image_url_safe('file:///etc/passwd'))
        self.assertFalse(validate_image_url_safe('javascript:alert(1)'))
        self.assertFalse(validate_image_url_safe(''))
        self.assertFalse(validate_image_url_safe(None))

        # Localhost / Loopback
        self.assertFalse(validate_image_url_safe('http://localhost/image.png'))
        self.assertFalse(validate_image_url_safe('http://127.0.0.1/image.png'))
        self.assertFalse(validate_image_url_safe('http://[::1]/image.png'))

        # Cloud Metadata endpoints
        self.assertFalse(validate_image_url_safe('http://169.254.169.254/latest/meta-data/'))
        self.assertFalse(validate_image_url_safe('http://metadata.google.internal/computeMetadata/v1/'))

        # Internal TLDs
        self.assertFalse(validate_image_url_safe('http://service.internal/img.png'))
        self.assertFalse(validate_image_url_safe('http://service.local/img.png'))

        # Private IP via DNS (mocked or direct IP)
        self.assertFalse(validate_image_url_safe('http://10.0.0.1/test.jpg'))
        self.assertFalse(validate_image_url_safe('http://192.168.1.1/test.jpg'))
        self.assertFalse(validate_image_url_safe('http://172.16.0.5/test.jpg'))

    def test_ssrf_guard_allows_safe_public_url(self):
        """Safe public HTTPS URLs pass validation."""
        with patch('socket.getaddrinfo') as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
            ]
            self.assertTrue(validate_image_url_safe('https://images.example.com/photo.jpg'))

    @patch('affiliate.services.image_cdn.requests.get')
    @patch('affiliate.services.image_cdn.validate_image_url_safe', return_value=True)
    def test_fetch_and_replicate_image_success(self, mock_validate, mock_get):
        """Test downloading remote image, calculating SHA-256 hash, and updating product."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = self.product.image_url
        mock_response.headers = {'Content-Type': 'image/jpeg'}
        dummy_content = b'fake-binary-image-data-closly'
        mock_response.iter_content.return_value = [dummy_content]
        mock_response.__enter__.return_value = mock_response
        mock_get.return_value = mock_response

        cdn_url = fetch_and_replicate_image(self.product)
        self.assertIsNotNone(cdn_url)

        self.product.refresh_from_db()
        self.assertTrue(self.product.cdn_image_url)
        self.assertTrue(self.product.image_hash)
        self.assertIsNotNone(self.product.image_replicated_at)
        expected_hash = hashlib.sha256(dummy_content).hexdigest()
        self.assertEqual(self.product.image_hash, expected_hash)
        self.assertIn(expected_hash, self.product.cdn_image_url)

    @patch('affiliate.services.image_cdn.requests.get')
    @patch('affiliate.services.image_cdn.validate_image_url_safe', return_value=True)
    def test_fetch_and_replicate_image_non_image_content_rejected(self, mock_validate, mock_get):
        """If remote URL returns HTML or executable, replication safely aborts."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = self.product.image_url
        mock_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        mock_response.__enter__.return_value = mock_response
        mock_get.return_value = mock_response

        cdn_url = fetch_and_replicate_image(self.product)
        self.assertIsNone(cdn_url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cdn_image_url, '')

    def test_purge_ended_brand_images(self):
        """AWIN compliance: ending a brand purges image URLs and deactivates catalog products."""
        self.product.cdn_image_url = 'https://cdn.myclosly.com/media/products/12/12345.jpg'
        self.product.save()

        self.brand.status = Brand.STATUS_ENDED
        self.brand.save()

        count = purge_ended_brand_images(self.brand)
        self.assertEqual(count, 1)

        self.product.refresh_from_db()
        self.assertEqual(self.product.cdn_image_url, '')
        self.assertEqual(self.product.image_url, '')
        self.assertFalse(self.product.is_active)

    def test_serializer_prefers_cdn_image_url(self):
        """Serializers should serve cdn_image_url over raw image_url when populated."""
        from affiliate.serializers import AffiliateProductListSerializer, AffiliateProductDetailSerializer

        # When cdn_image_url is empty
        serializer_list = AffiliateProductListSerializer(self.product)
        self.assertEqual(serializer_list.data['image_url'], self.product.image_url)

        # When cdn_image_url is set
        self.product.cdn_image_url = 'https://cdn.myclosly.com/media/products/ab/abcdef123.jpg'
        self.product.save()

        serializer_list = AffiliateProductListSerializer(self.product)
        self.assertEqual(serializer_list.data['image_url'], 'https://cdn.myclosly.com/media/products/ab/abcdef123.jpg')

        serializer_detail = AffiliateProductDetailSerializer(self.product)
        self.assertEqual(serializer_detail.data['image_url'], 'https://cdn.myclosly.com/media/products/ab/abcdef123.jpg')


class AffiliateConversionWebhookTests(APITestCase):
    """
    Tests for Audit Item CF-30:
    - AWIN Server-to-Server webhook endpoint (/api/affiliate/webhooks/awin/)
    - Authentication validation (token / bearer / signature)
    - Click reference attribution linkage (clickref -> ProductClick -> User)
    - Unknown click reference graceful handling
    - Database idempotency on repeated webhooks (UniqueConstraint)
    - Status transitions (pending -> approved)
    - Product and Brand linkage fallback
    - Rewards integration reconciliation
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='Password123!',
            name='Buyer User',
        )
        self.brand = Brand.objects.create(
            name='Zara',
            slug='zara',
            external_id='12345',
            status=Brand.STATUS_ACTIVE,
        )
        self.product = AffiliateProduct.objects.create(
            aw_product_id='aw_prod_999',
            brand_ref=self.brand,
            name='Zara Tweed Jacket',
            brand='Zara',
            price=decimal.Decimal('120.00'),
            currency='GBP',
            image_url='https://example.com/jacket.jpg',
            is_active=True,
        )
        self.click_ref = uuid.uuid4()
        self.click = ProductClick.objects.create(
            user=self.user,
            product=self.product,
            click_ref=self.click_ref,
            surface='newsfeed',
            user_agent_hash='abc123hash',
            ip_prefix='198.51.100.0/24',
        )
        self.webhook_url = reverse('affiliate:webhook-awin')
        self.secret = 'test-awin-webhook-secret-xyz'

    def post_webhook(self, data, **extra):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.secret}'}
        headers.update(extra)
        with self.settings(MYC_AWIN_WEBHOOK_SECRET=self.secret):
            return self.client.post(self.webhook_url, data=data, format='json', **headers)

    def test_unauthorized_webhook_rejected(self):
        """When MYC_AWIN_WEBHOOK_SECRET is set, requests without valid token get 401."""
        with self.settings(MYC_AWIN_WEBHOOK_SECRET='super-secret-token'):
            res = self.client.post(self.webhook_url, data={'id': 'tx-1'}, format='json')
            self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authorized_webhook_bearer_token(self):
        """Valid Bearer token allows webhook ingestion."""
        payload = {
            'id': 'tx-1001',
            'clickref': str(self.click_ref),
            'amount': '120.00',
            'commission': '12.00',
            'currency': 'GBP',
            'status': 'pending',
            'advertiser_id': '12345',
            'order_reference': 'ORD-9876',
        }
        res = self.post_webhook(payload)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['data']['created'], 1)

        conversion = Conversion.objects.get(conversion_id='tx-1001')
        self.assertEqual(conversion.click, self.click)
        self.assertEqual(conversion.user, self.user)
        self.assertEqual(conversion.product, self.product)
        self.assertEqual(conversion.brand, self.brand)
        self.assertEqual(conversion.status, Conversion.STATUS_PENDING)
        self.assertEqual(conversion.sale_amount, decimal.Decimal('120.00'))
        self.assertEqual(conversion.commission_amount, decimal.Decimal('12.00'))
        self.assertEqual(conversion.currency, 'GBP')
        self.assertEqual(conversion.order_reference, 'ORD-9876')

    def test_idempotent_duplicate_webhook_does_not_duplicate_rows(self):
        """Sending the exact same transaction ID updates existing record rather than inserting new."""
        payload = {
            'id': 'tx-unique-200',
            'clickref': str(self.click_ref),
            'amount': '85.50',
            'commission': '8.55',
            'currency': 'EUR',
            'status': 'pending',
        }
        # First post -> created
        res1 = self.post_webhook(payload)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data['data']['created'], 1)
        self.assertEqual(Conversion.objects.filter(conversion_id='tx-unique-200').count(), 1)

        # Second post identical -> updated, no new row
        res2 = self.post_webhook(payload)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['data']['created'], 0)
        self.assertEqual(res2.data['data']['updated'], 1)
        self.assertEqual(Conversion.objects.filter(conversion_id='tx-unique-200').count(), 1)

    def test_status_transition_pending_to_approved_and_rewards_award(self):
        """A transaction updating from pending to approved updates status and awards reward points."""
        payload_pending = {
            'id': 'tx-transition-300',
            'clickref': str(self.click_ref),
            'amount': '150.00',
            'commission': '15.00',
            'currency': 'EUR',
            'status': 'pending',
            'order_reference': 'ORDER-TRANS-300',
        }
        res_p = self.post_webhook(payload_pending)
        self.assertEqual(res_p.status_code, status.HTTP_200_OK)

        conv = Conversion.objects.get(conversion_id='tx-transition-300')
        self.assertEqual(conv.status, Conversion.STATUS_PENDING)
        self.assertFalse(conv.reward_claimed)

        # Send approved status transition
        payload_approved = {
            'id': 'tx-transition-300',
            'clickref': str(self.click_ref),
            'amount': '150.00',
            'commission': '15.00',
            'currency': 'EUR',
            'status': 'approved',
            'order_reference': 'ORDER-TRANS-300',
        }
        res_a = self.post_webhook(payload_approved)
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)

        conv.refresh_from_db()
        self.assertEqual(conv.status, Conversion.STATUS_APPROVED)
        self.assertTrue(conv.reward_claimed)
        self.assertIsNotNone(conv.reward_transaction)
        self.assertIsNotNone(conv.validation_date)

    def test_unknown_click_ref_handled_gracefully(self):
        """Unknown or missing clickref does not crash; transaction is preserved safely."""
        unknown_uuid = str(uuid.uuid4())
        payload = {
            'id': 'tx-orphan-400',
            'clickref': unknown_uuid,
            'amount': '50.00',
            'commission': '5.00',
            'currency': 'USD',
            'status': 'approved',
        }
        res = self.post_webhook(payload)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        conv = Conversion.objects.get(conversion_id='tx-orphan-400')
        self.assertIsNone(conv.click)
        self.assertIsNone(conv.user)
        self.assertEqual(str(conv.click_ref), unknown_uuid)
        self.assertEqual(conv.status, Conversion.STATUS_APPROVED)

    def test_missing_tx_id_or_empty_payload(self):
        """Invalid or empty payload returns 400."""
        res_empty = self.post_webhook({})
        self.assertEqual(res_empty.status_code, status.HTTP_400_BAD_REQUEST)

        # Payload without id or transaction_id
        res_no_id = self.post_webhook({'clickref': 'test'})
        self.assertEqual(res_no_id.status_code, status.HTTP_200_OK)
        self.assertEqual(res_no_id.data['data']['processed'], 0)

    def test_product_fallback_linkage_via_product_id(self):
        """When clickref is absent, product can still link via merchant_product_id or aw_product_id."""
        payload = {
            'id': 'tx-direct-500',
            'aw_product_id': 'aw_prod_999',
            'amount': '120.00',
            'currency': 'GBP',
            'status': 'pending',
        }
        res = self.post_webhook(payload)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        conv = Conversion.objects.get(conversion_id='tx-direct-500')
        self.assertEqual(conv.product, self.product)
        self.assertEqual(conv.brand, self.brand)

