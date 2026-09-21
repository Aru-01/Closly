from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import AffiliateProduct

class AffiliateAPITests(APITestCase):
    """
    Test suite for the Affiliate product newsfeed and filters API endpoints.
    """
    def setUp(self):
        # Create test affiliate products
        self.product1 = AffiliateProduct.objects.create(
            aw_product_id="test_aw_1",
            name="Zara Summer Floral Dress",
            brand="Zara",
            description="A beautiful floral dress.",
            price=49.99,
            currency="GBP",
            image_url="https://example.com/zara-dress.jpg",
            aw_deep_link="https://awin1.com/zara-dress",
            category="Womenswear > Dresses",
            advertiser_name="Zara Retail",
            is_active=True
        )
        
        self.product2 = AffiliateProduct.objects.create(
            aw_product_id="test_aw_2",
            name="H&M Oxford Shirt",
            brand="H&M",
            description="Classic button-down shirt.",
            price=29.99,
            currency="GBP",
            image_url="https://example.com/hm-shirt.jpg",
            aw_deep_link="https://awin1.com/hm-shirt",
            category="Menswear > Shirts",
            advertiser_name="H&M Retail",
            is_active=True
        )

        self.inactive_product = AffiliateProduct.objects.create(
            aw_product_id="test_aw_3",
            name="Nike Inactive Sneakers",
            brand="Nike",
            description="Comfortable running sneakers.",
            price=89.99,
            currency="GBP",
            image_url="https://example.com/nike-sneakers.jpg",
            aw_deep_link="https://awin1.com/nike-sneakers",
            category="Footwear > Sneakers",
            advertiser_name="Nike Retail",
            is_active=False
        )

    def test_get_newsfeed_products(self):
        """Test retrieving all active affiliate products from the newsfeed."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        # Only active products should be returned (2 active, 1 inactive)
        self.assertEqual(len(response.data['data']['results']), 2)
        self.assertEqual(response.data['data']['count'], 2)

    def test_filter_by_brand(self):
        """Test filtering products in the newsfeed by brand name."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url, {'brand': 'Zara'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['results']), 1)
        self.assertEqual(response.data['data']['results'][0]['brand'], 'Zara')

    def test_search_products(self):
        """Test text searching in the newsfeed."""
        url = reverse('affiliate:products-feed')
        response = self.client.get(url, {'search': 'Oxford'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['results']), 1)
        self.assertEqual(response.data['data']['results'][0]['name'], 'H&M Oxford Shirt')

    def test_get_brands_list(self):
        """Test fetching the list of all unique active brands."""
        url = reverse('affiliate:brands-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        # Inactive brand 'Nike' should not be in the list
        brand_names = [b['brand'] for b in response.data['data']['brands']]
        self.assertIn('Zara', brand_names)
        self.assertIn('H&M', brand_names)
        self.assertNotIn('Nike', brand_names)

    def test_get_categories_list(self):
        """Test fetching the list of unique active categories."""
        url = reverse('affiliate:categories-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        category_names = [c['category'] for c in response.data['data']['categories']]
        self.assertIn('Womenswear > Dresses', category_names)
        self.assertIn('Menswear > Shirts', category_names)
        self.assertNotIn('Footwear > Sneakers', category_names)

    def test_for_you_products_personalized(self):
        """Test personalized For You feed prioritizing user taste profile."""
        from django.contrib.auth import get_user_model
        from users.models import UserPreference

        User = get_user_model()
        user = User.objects.create_user(
            email='foryouuser@example.com',
            password='Password123!',
            name='For You User'
        )
        UserPreference.objects.create(
            user=user,
            preferred_brands=['Zara'],
            color_palette='neutral_minimalist',
            style_match=['minimalist']
        )
        self.client.force_authenticate(user=user)

        url = reverse('affiliate:products-for-you')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('user_taste_profile', response.data)
        self.assertEqual(response.data['user_taste_profile']['preferred_brands'], ['Zara'])
        results = response.data['data']['results']
        self.assertGreaterEqual(len(results), 1)
        # Zara product should rank top because user prefers Zara
        self.assertEqual(results[0]['brand'], 'Zara')

    def test_product_favorite_toggle_and_saved_list(self):
        """Test user can love/save product and retrieve it in their saved wishlist."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            email='shopper@example.com',
            password='Password123!',
            name='Shopper User'
        )
        self.client.force_authenticate(user=user)

        # 1. Love the Zara product
        love_url = reverse('affiliate:product-love', kwargs={'pk': self.product1.pk})
        res = self.client.post(love_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['data']['status'], 'loved')
        self.assertTrue(res.data['data']['is_loved'])
        self.assertEqual(res.data['data']['favorites_count'], 1)

        # 2. Check saved products list
        saved_url = reverse('affiliate:products-saved')
        res_saved = self.client.get(saved_url)
        self.assertEqual(res_saved.status_code, status.HTTP_200_OK)
        saved_items = res_saved.data['data']['results']
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0]['id'], self.product1.id)
        self.assertTrue(saved_items[0]['is_loved'])
        self.assertEqual(saved_items[0]['favorites_count'], 1)

        # 3. Unlove the product
        res_unlove = self.client.post(love_url)
        self.assertEqual(res_unlove.status_code, status.HTTP_200_OK)
        self.assertEqual(res_unlove.data['data']['status'], 'unloved')
        self.assertFalse(res_unlove.data['data']['is_loved'])

        # 4. Check saved products list is now empty
        res_saved2 = self.client.get(saved_url)
        self.assertEqual(len(res_saved2.data['data']['results']), 0)

    def test_for_you_male_gender_ratio_65_35(self):
        """Test Male user receives 65% male/unisex and 35% female products in For You feed."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Create male products
        for i in range(15):
            AffiliateProduct.objects.create(
                aw_product_id=f'test_male_unit_{i}',
                name=f'Nike Air Training Sneaker {i}',
                brand='Nike',
                category='Clothing & Accessories > Shoes & Boots',
                price=50.00,
                is_active=True
            )
        # Create female products
        for i in range(15):
            AffiliateProduct.objects.create(
                aw_product_id=f'test_female_unit_{i}',
                name=f'Floral Summer Dress {i}',
                brand='Twinset',
                category="Women's Dresses & Skirts",
                price=50.00,
                is_active=True
            )

        male_user = User.objects.create_user(
            email='male_ratio_tester@example.com',
            name='Male Ratio Tester',
            password='Password123!',
            gender='male'
        )
        self.client.force_authenticate(user=male_user)

        url = reverse('affiliate:products-for-you') + '?page=1&page_size=20'
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['gender_balance']['user_gender'], 'male')
        self.assertEqual(res.data['gender_balance']['primary_ratio'], '65%')
        self.assertEqual(res.data['gender_balance']['secondary_ratio'], '35%')

        results = res.data['data']['results']
        self.assertEqual(len(results), 20)

        male_items = [p for p in results if 'Dress' not in p['name']]
        female_items = [p for p in results if 'Dress' in p['name']]

        self.assertEqual(len(male_items), 13) # 65% of 20
        self.assertEqual(len(female_items), 7)  # 35% of 20

    def test_for_you_female_gender_ratio_65_35(self):
        """Test Female user receives 65% female and 35% male/unisex products in For You feed."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Create male products
        for i in range(15):
            AffiliateProduct.objects.create(
                aw_product_id=f'test_male_f_unit_{i}',
                name=f'Adidas Track Jacket {i}',
                brand='Adidas',
                category='Clothing & Accessories > Jackets & Coats',
                price=60.00,
                is_active=True
            )
        # Create female products
        for i in range(15):
            AffiliateProduct.objects.create(
                aw_product_id=f'test_female_f_unit_{i}',
                name=f'Evening Silk Midi Dress {i}',
                brand='Twinset',
                category="Women's Dresses & Skirts",
                price=90.00,
                is_active=True
            )

        female_user = User.objects.create_user(
            email='female_ratio_tester@example.com',
            name='Female Ratio Tester',
            password='Password123!',
            gender='female'
        )
        self.client.force_authenticate(user=female_user)

        url = reverse('affiliate:products-for-you') + '?page=1&page_size=20'
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['gender_balance']['user_gender'], 'female')

        results = res.data['data']['results']
        self.assertEqual(len(results), 20)

        female_items = [p for p in results if 'Dress' in p['name']]
        male_items = [p for p in results if 'Dress' not in p['name']]

        self.assertEqual(len(female_items), 13) # 65% of 20
        self.assertEqual(len(male_items), 7)   # 35% of 20


