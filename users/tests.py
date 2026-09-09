from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from users.models import UserPreference

User = get_user_model()

class UserPreferenceAndLoginTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='TestPassword123!',
            name='Test User',
            is_active=True,
            is_email_verified=True
        )

    def test_login_returns_onboarding_status(self):
        url = reverse('users:login')
        response = self.client.post(url, {
            'email': 'testuser@example.com',
            'password': 'TestPassword123!'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('onboarding_completed', response.data['data']['user'])
        self.assertEqual(response.data['data']['user']['onboarding_completed'], False)

    def test_preferences_dress_for_get_and_post(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('users:user-preferences')
        
        # Test GET
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertIn('dress_for_options', get_res.data['data'])
        self.assertIn('what_do_you_dress_for', get_res.data['data'])
        
        # Test POST
        post_res = self.client.post(url, {
            'what_do_you_dress_for': ['work-casual', 'weekend', 'going-out']
        }, format='json')
        self.assertEqual(post_res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            post_res.data['data']['what_do_you_dress_for'],
            ['work-casual', 'weekend', 'going-out']
        )
        self.assertEqual(post_res.data['data']['onboarding_completed'], True)

        # Test login after completing onboarding
        self.client.logout()
        login_url = reverse('users:login')
        login_res = self.client.post(login_url, {
            'email': 'testuser@example.com',
            'password': 'TestPassword123!'
        }, format='json')
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)
        self.assertEqual(login_res.data['data']['user']['onboarding_completed'], True)

