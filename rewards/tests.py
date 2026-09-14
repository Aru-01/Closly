from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone
from datetime import timedelta

from .models import UserRewardProfile, RewardPointTransaction
from .services import award_points, process_expired_points, get_tier_info

User = get_user_model()


class RewardPointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='rewarduser@example.com', password='Password123!', name='Reward User')
        self.client.force_authenticate(user=self.user)

    def test_earning_points_and_new_tier_thresholds(self):
        # 1. Earn 120 (share look) + 50 (add item) = 170
        award_points(self.user, 'share_look')
        award_points(self.user, 'add_closet_item')

        profile = UserRewardProfile.objects.get(user=self.user)
        self.assertEqual(profile.available_points, 170)
        self.assertEqual(profile.lifetime_points, 170)
        self.assertEqual(profile.current_tier, 'Bronze')

        # 2. Advance to Silver (threshold: 2,000)
        award_points(self.user, 'custom_reward', points_override=1850)
        profile.refresh_from_db()
        self.assertEqual(profile.lifetime_points, 2020)
        self.assertEqual(profile.current_tier, 'Silver')

        # 3. Advance to Gold (threshold: 5,000)
        award_points(self.user, 'custom_reward', points_override=3000)
        profile.refresh_from_db()
        self.assertEqual(profile.lifetime_points, 5020)
        self.assertEqual(profile.current_tier, 'Gold')

        # 4. Advance to Platinum (threshold: 10,000)
        award_points(self.user, 'custom_reward', points_override=5000)
        profile.refresh_from_db()
        self.assertEqual(profile.lifetime_points, 10020)
        self.assertEqual(profile.current_tier, 'Platinum')

        # 5. Advance to Diamond (threshold: 50,000)
        award_points(self.user, 'custom_reward', points_override=40000)
        profile.refresh_from_db()
        self.assertEqual(profile.lifetime_points, 50020)
        self.assertEqual(profile.current_tier, 'Diamond')

    def test_60_day_expiration_and_tier_preservation(self):
        # User earns 2,500 points (qualifying for Silver tier: >= 2,000)
        tx = award_points(self.user, 'custom_reward', points_override=2500)
        profile = UserRewardProfile.objects.get(user=self.user)
        self.assertEqual(profile.available_points, 2500)
        self.assertEqual(profile.lifetime_points, 2500)
        self.assertEqual(profile.current_tier, 'Silver')

        # Simulate that 61 days have passed (transaction is now expired)
        past_date = timezone.now() - timedelta(days=61)
        tx.expires_at = past_date
        tx.save(update_fields=['expires_at'])

        # Process expiration
        expired_count = process_expired_points(self.user)
        self.assertEqual(expired_count, 2500)

        profile.refresh_from_db()
        # available_points is now 0 because points expired
        self.assertEqual(profile.available_points, 0)

        # But lifetime_points NEVER decreases upon expiry!
        self.assertEqual(profile.lifetime_points, 2500)
        # Therefore, user's earned Silver tier is permanently preserved!
        self.assertEqual(profile.current_tier, 'Silver')

    def test_reward_api_endpoints(self):
        award_points(self.user, 'share_look') # +120

        # Summary API
        res = self.client.get('/api/rewards/points/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data['data']
        self.assertEqual(data['available_points'], 120)
        self.assertEqual(data['lifetime_points'], 120)
        self.assertEqual(data['current_tier'], 'Bronze')
        self.assertEqual(data['next_tier'], 'Silver')
        self.assertEqual(data['points_to_next_tier'], 1880)

        # History API
        h_res = self.client.get('/api/rewards/points/history/')
        self.assertEqual(h_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(h_res.data['data']), 1)

        # Claim Purchase API (+200)
        claim_res = self.client.post('/api/rewards/points/claim-purchase/', {
            'order_id': 'ORD-5501',
            'store': 'Zara',
            'amount': '129.00'
        }, format='json')
        self.assertEqual(claim_res.status_code, status.HTTP_200_OK)
        self.assertEqual(claim_res.data['data']['points_awarded'], 200)

        # Duplicate order claim rejected
        dup_res = self.client.post('/api/rewards/points/claim-purchase/', {
            'order_id': 'ORD-5501',
            'store': 'Zara',
        }, format='json')
        self.assertEqual(dup_res.status_code, status.HTTP_400_BAD_REQUEST)
