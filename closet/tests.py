from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from .models import ClosetItem

User = get_user_model()

class ClosetApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='closetuser@example.com',
            password='Password123!',
            name='Closet User'
        )
        self.client.force_authenticate(user=self.user)

    def test_create_and_list_closet_item(self):
        url = '/api/closet/items/'
        data = {
            'name': 'Test Jacket',
            'category': 'top',
            'color': 'Black',
            'brand': 'Zara',
            'size': 'L',
            'price': '100.00'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['name'], 'Test Jacket')
        self.assertEqual(response.data['data']['per_wear_cost'], 100.00)

        # Test Wear Today
        item_id = response.data['data']['id']
        wear_url = f'/api/closet/items/{item_id}/wear-today/'
        wear_response = self.client.post(wear_url)
        self.assertEqual(wear_response.status_code, status.HTTP_200_OK)
        self.assertEqual(wear_response.data['data']['times_worn'], 1)
        self.assertEqual(wear_response.data['data']['per_wear_cost'], 100.00)

    def test_closet_audit(self):
        from django.utils import timezone
        ClosetItem.objects.create(user=self.user, name='Item 1', category='top', price=50.00, times_worn=5, last_worn_at=timezone.now())
        ClosetItem.objects.create(user=self.user, name='Item 2', category='bottom', price=30.00, times_worn=0)

        url = '/api/closet/audit/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['total_pieces'], 2)
        self.assertEqual(data['active_pieces'], 1)
        self.assertEqual(data['ghost_pieces'], 1)
        self.assertEqual(len(data['list_of_most_worn']), 1)
        self.assertEqual(len(data['list_of_ghost_pieces']), 1)
        self.assertIn('environmental_and_space_impact', data)
        self.assertIn('wasted_carbon_kg', data['environmental_and_space_impact'])
        self.assertIn('wardrobe_status', data)
        self.assertIn('badge', data['wardrobe_status'])

    def test_closet_score_dashboard(self):
        url = '/api/closet/score/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertIn('closet_score', data)
        self.assertIn('category', data)
        self.assertIn('cost_wear', data)
        self.assertIn('closet_points', data)
        self.assertIn('achieve_rank', data)
        self.assertIn('style_dna', data)

    def test_negative_price_rejected(self):
        url = '/api/closet/items/'
        data = {
            'name': 'Negative Price Jacket',
            'category': 'top',
            'price': '-25.00'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('price', response.data['errors'])

    def test_image_size_and_format_validation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from users.validators import validate_image_file

        # Test invalid extension
        bad_format_file = SimpleUploadedFile("test.exe", b"fake binary data", content_type="application/octet-stream")
        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(bad_format_file, max_mb=30)
        self.assertIn("Only JPG, JPEG, PNG, GIF, WebP, and HEIC", str(ctx.exception))

        # Test oversized file (> 30MB)
        # Mock size attribute to avoid allocating 31MB in memory
        class MockLargeFile:
            name = "large.jpg"
            size = 31 * 1024 * 1024

        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(MockLargeFile(), max_mb=30)
        self.assertIn("exceeds the 30MB limit", str(ctx.exception))

