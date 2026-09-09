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
        self.assertEqual(response.data['data']['total_items'], 2)
        self.assertEqual(len(response.data['data']['ghost_pieces']), 1)
