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

    def test_closet_points_and_gamification_tiers(self):
        from rewards.services import award_points, get_tier_info
        from rewards.models import UserRewardProfile, RewardPointTransaction

        self.client.force_authenticate(user=self.user)

        # 1. Award share_look (+120)
        t1 = award_points(self.user, 'share_look')
        self.assertEqual(t1.points, 120)

        # 2. Award add_closet_item (+50)
        t2 = award_points(self.user, 'add_closet_item')
        self.assertEqual(t2.points, 50)

        # 3. Check summary via API
        points_res = self.client.get(reverse('users:points-summary'))
        self.assertEqual(points_res.status_code, status.HTTP_200_OK)
        data = points_res.data['data']
        self.assertEqual(data['total_points'], 170)
        self.assertEqual(data['current_tier'], 'Bronze')
        self.assertEqual(data['next_tier'], 'Silver')
        self.assertEqual(data['points_to_next_tier'], 1830)

        # 4. Check history via API
        history_res = self.client.get(reverse('users:points-history'))
        self.assertEqual(history_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history_res.data['data']), 2)

        # 5. Claim purchase points (+200)
        claim_res = self.client.post(reverse('users:claim-purchase-points'), {
            'order_id': 'ORDER-99182',
            'store': 'H&M',
            'amount': '85.50'
        }, format='json')
        self.assertEqual(claim_res.status_code, status.HTTP_200_OK)
        self.assertEqual(claim_res.data['data']['points_awarded'], 200)

        # Duplicate claim should be rejected
        dup_res = self.client.post(reverse('users:claim-purchase-points'), {
            'order_id': 'ORDER-99182',
            'store': 'H&M',
        }, format='json')
        self.assertEqual(dup_res.status_code, status.HTTP_400_BAD_REQUEST)

        # 6. Level up to Silver by adding points to reach 2,000 threshold
        # Current: 170 + 200 = 370. Need 1630 more.
        award_points(self.user, 'custom_reward', points_override=1630)
        profile = UserRewardProfile.objects.get(user=self.user)
        self.assertEqual(profile.available_points, 2000)
        self.assertEqual(profile.current_tier, 'Silver')

    def test_referral_award_on_registration(self):
        from rewards.models import UserRewardProfile

        # User 1 has a referral code
        self.assertTrue(self.user.referral_code.startswith('CLO-'))
        ref_code = self.user.referral_code

        # New user signs up with User 1's referral code
        signup_url = reverse('users:signup')
        signup_data = {
            'name': 'Friend User',
            'email': 'friend@example.com',
            'date_of_birth': '1998-08-20',
            'gender': 'female',
            'password': 'FriendPassword123!',
            'confirm_password': 'FriendPassword123!',
            'referral_code': ref_code
        }
        res = self.client.post(signup_url, signup_data, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # User 1 should have received +200 points for inviting a friend!
        profile = UserRewardProfile.objects.filter(user=self.user).first()
        self.assertIsNotNone(profile)
        self.assertGreaterEqual(profile.available_points, 200)

    def test_profile_sharing_and_public_landing(self):
        self.client.force_authenticate(user=self.user)

        # 1. Get share info via API
        share_res = self.client.get(reverse('users:profile-share'))
        self.assertEqual(share_res.status_code, status.HTTP_200_OK)
        self.assertIn('share_url', share_res.data['data'])
        self.assertIn('referral_code', share_res.data['data'])
        self.assertIn('deep_link', share_res.data['data'])

        # 2. Public web landing page
        landing_url = f'/u/{self.user.id}/'
        landing_res = self.client.get(landing_url)
        self.assertEqual(landing_res.status_code, status.HTTP_200_OK)
        self.assertContains(landing_res, self.user.name)
        self.assertContains(landing_res, self.user.referral_code)



