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

    def test_unverified_user_reregistration_flow(self):
        signup_url = reverse('users:signup')
        signup_data = {
            'name': 'New Unverified',
            'email': 'unverified@example.com',
            'date_of_birth': '1995-05-15',
            'gender': 'female',
            'password': 'InitialPassword123!',
            'confirm_password': 'InitialPassword123!'
        }

        # 1. First signup attempt
        res1 = self.client.post(signup_url, signup_data, format='json')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='unverified@example.com')
        self.assertFalse(user.is_email_verified)
        initial_otp = user.otp

        # 2. Second signup attempt while still unverified (UX fix)
        signup_data['name'] = 'Updated Name'
        signup_data['password'] = 'NewPassword123!'
        signup_data['confirm_password'] = 'NewPassword123!'
        res2 = self.client.post(signup_url, signup_data, format='json')
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        user.refresh_from_db()
        self.assertEqual(user.name, 'Updated Name')
        self.assertTrue(user.check_password('NewPassword123!'))

        # 3. Verify user and ensure subsequent signup fails
        user.is_email_verified = True
        user.save()
        res3 = self.client.post(signup_url, signup_data, format='json')
        self.assertEqual(res3.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verified", str(res3.data['errors']['email']))

    def test_email_sending_failure_does_not_crash(self):
        from unittest.mock import patch

        with patch('users.views.send_mail', side_effect=Exception("SMTP Connection Refused")):
            # Profile data deletion
            req_url1 = reverse('users:delete-profile-data-request')
            res1 = self.client.post(req_url1, {'email': 'testuser@example.com'})
            self.assertEqual(res1.status_code, status.HTTP_200_OK)

            # Account deletion
            req_url2 = reverse('users:delete-account-request')
            res2 = self.client.post(req_url2, {'name': 'Test User', 'email': 'testuser@example.com'})
            self.assertEqual(res2.status_code, status.HTTP_200_OK)

    def test_translation_middleware_filters(self):
        from users.middleware import TranslationMiddleware

        middleware = TranslationMiddleware(get_response=lambda r: None)

        # Technical values that should be skipped
        self.assertTrue(middleware._should_skip_string('#FFFFFF'))
        self.assertTrue(middleware._should_skip_string('#fff'))
        self.assertTrue(middleware._should_skip_string('https://example.com/pic.jpg'))
        self.assertTrue(middleware._should_skip_string('/media/closet/pic.jpg'))
        self.assertTrue(middleware._should_skip_string('12345'))
        self.assertTrue(middleware._should_skip_string('-49.99'))
        self.assertTrue(middleware._should_skip_string('a63b2f8a-9e12-4c56-8a4b-22ef901b0051'))
        self.assertTrue(middleware._should_skip_string('2026-09-14T12:00:00Z'))
        self.assertTrue(middleware._should_skip_string('user@closly.com'))

        # Normal text should not be skipped
        self.assertFalse(middleware._should_skip_string('Welcome to your closet'))
        self.assertFalse(middleware._should_skip_string('Casual Friday outfit with a white tee'))


