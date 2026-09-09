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
