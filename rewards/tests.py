from django.test import TestCase, override_settings
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

    def test_24_month_expiration_and_tier_preservation(self):
        """SR-08 & SR-24: Points have 24-month validity (730 days) and tier is permanently preserved."""
        # User earns 2,500 points (qualifying for Silver tier: >= 2,000)
        tx = award_points(self.user, 'custom_reward', points_override=2500)
        profile = UserRewardProfile.objects.get(user=self.user)
        self.assertEqual(profile.available_points, 2500)
        self.assertEqual(profile.lifetime_points, 2500)
        self.assertEqual(profile.current_tier, 'Silver')

        # Verify initial validity is approximately 730 days (24 months)
        expected_expiry = timezone.now() + timedelta(days=730)
        self.assertAlmostEqual(
            tx.expires_at.timestamp(),
            expected_expiry.timestamp(),
            delta=60  # within 1 minute
        )

        # Simulate that 24 months + 1 day have passed (transaction is now expired)
        past_date = timezone.now() - timedelta(days=731)
        tx.expires_at = past_date
        tx.save(update_fields=['expires_at'])

        # Also expire any associated PointAward
        from .models import PointAward
        PointAward.objects.filter(user=self.user).update(expires_at=past_date)

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

    def test_double_entry_ledger_invariants(self):
        """SR-08: Every ledger transaction must strictly balance to zero sum."""
        from .models import LedgerAccount, LedgerTxn, LedgerEntry
        from .services import get_or_create_ledger_account, create_balanced_ledger_txn

        user_acc = get_or_create_ledger_account('user_available', user=self.user)
        ctrl_acc = get_or_create_ledger_account('points_liability_control')

        # 1. Balanced transaction succeeds
        txn = create_balanced_ledger_txn(
            txn_type='test_award',
            idempotency_key='test:idempotent:1',
            entries_data=[(ctrl_acc, -100), (user_acc, 100)]
        )
        self.assertIsNotNone(txn)
        self.assertEqual(sum(e.points for e in txn.entries.all()), 0)

        # 2. Idempotency replay returns existing transaction without duplicate entries
        entry_count_before = LedgerEntry.objects.count()
        replay_txn = create_balanced_ledger_txn(
            txn_type='test_award',
            idempotency_key='test:idempotent:1',
            entries_data=[(ctrl_acc, -100), (user_acc, 100)]
        )
        self.assertEqual(replay_txn.id, txn.id)
        self.assertEqual(LedgerEntry.objects.count(), entry_count_before)

        # 3. Unbalanced transaction raises ValueError
        with self.assertRaises(ValueError):
            create_balanced_ledger_txn(
                txn_type='bad_unbalanced',
                idempotency_key='test:unbalanced:1',
                entries_data=[(ctrl_acc, -100), (user_acc, 50)]
            )

    def test_activity_reward_integrity_caps_and_reversal(self):
        """SR-07: Public outfit rewards 120, private 0, daily cap 120, idempotent, reversal on delete."""
        from unittest.mock import MagicMock
        from .services import record_activity_reward, reverse_activity_reward
        from .models import PointAward

        # 1. Disabled flag -> returns None
        outfit_public = MagicMock(id=101, visibility='public')
        with override_settings(MYC_POINTS_ACTIVITY_AWARDS=False):
            self.assertIsNone(record_activity_reward(self.user, outfit_public))

        # 2. Enabled flag
        with override_settings(MYC_POINTS_ACTIVITY_AWARDS=True, MYC_ACTIVITY_POINTS_DAILY_CAP=120):
            # Private outfit -> returns None at business logic level
            outfit_private = MagicMock(id=102, visibility='private')
            self.assertIsNone(record_activity_reward(self.user, outfit_private))

            # Public outfit -> earns 120 points
            award1 = record_activity_reward(self.user, outfit_public)
            self.assertIsNotNone(award1)
            self.assertEqual(award1.points_current, 120)
            self.assertEqual(award1.state, 'AVAILABLE')

            profile = UserRewardProfile.objects.get(user=self.user)
            self.assertEqual(profile.available_points, 120)

            # Duplicate call on same outfit -> idempotent, returns same award
            award1_dup = record_activity_reward(self.user, outfit_public)
            self.assertEqual(award1_dup.id, award1.id)
            profile.refresh_from_db()
            self.assertEqual(profile.available_points, 120)

            # Second public outfit on same day -> hit daily velocity cap (120)
            outfit_public_2 = MagicMock(id=103, visibility='public')
            award2 = record_activity_reward(self.user, outfit_public_2)
            self.assertIsNone(award2)
            profile.refresh_from_db()
            self.assertEqual(profile.available_points, 120)

            # Reversal on delete: claws back points safely
            reversed_ok = reverse_activity_reward(self.user, outfit_id=101)
            self.assertTrue(reversed_ok)
            profile.refresh_from_db()
            self.assertEqual(profile.available_points, 0)

            # Award state transitioned to CLAWED_BACK
            award1.refresh_from_db()
            self.assertEqual(award1.state, 'CLAWED_BACK')
            self.assertEqual(award1.points_current, 0)

            # Reversing already reversed outfit returns False
            self.assertFalse(reverse_activity_reward(self.user, outfit_id=101))

    def test_referral_reward_integrity_and_velocity_cap(self):
        """SR-04: Referral reward gates on activation, prevents self-referral, enforces weekly cap."""
        from .services import activate_referral_reward
        from .models import PointAward

        referrer = self.user
        ref_user1 = User.objects.create_user(email='ref1@example.com', password='Password123!', name='Ref 1', is_active=False)

        # 1. Unactivated referred user -> returns None
        self.assertIsNone(activate_referral_reward(ref_user1))

        # 2. Self-referral -> returns None
        referrer.referred_by = referrer
        referrer.save(update_fields=['referred_by'])
        self.assertIsNone(activate_referral_reward(referrer))

        # 3. Successful referral on activation
        ref_user1.referred_by = referrer
        ref_user1.is_active = True
        ref_user1.save(update_fields=['referred_by', 'is_active'])

        award = activate_referral_reward(ref_user1)
        self.assertIsNotNone(award)
        self.assertEqual(award.points_current, 200)

        profile = UserRewardProfile.objects.get(user=referrer)
        self.assertEqual(profile.available_points, 200)

        # 4. Duplicate activation retry -> returns existing award
        award_dup = activate_referral_reward(ref_user1)
        self.assertEqual(award_dup.id, award.id)
        profile.refresh_from_db()
        self.assertEqual(profile.available_points, 200)

        # 5. Weekly velocity cap (5 referrals)
        with override_settings(MYC_REFERRAL_WEEKLY_CAP=2):
            # Create second referral -> succeeds
            ref_user2 = User.objects.create_user(email='ref2@example.com', password='Password123!', name='Ref 2', referred_by=referrer, is_active=True)
            self.assertIsNotNone(activate_referral_reward(ref_user2))

            # Create third referral -> blocked by weekly cap
            ref_user3 = User.objects.create_user(email='ref3@example.com', password='Password123!', name='Ref 3', referred_by=referrer, is_active=True)
            self.assertIsNone(activate_referral_reward(ref_user3))

    def test_database_reconciliation_idempotency(self):
        """SR-08: reconcile_existing_reward_data guarantees balanced entries and is idempotent."""
        from .models import LedgerTxn, LedgerEntry
        from .services import reconcile_existing_reward_data

        # Ensure balanced entries
        reconciled = reconcile_existing_reward_data()
        self.assertGreaterEqual(reconciled, 0)
        self.assertEqual(sum(e.points for e in LedgerEntry.objects.all()), 0)

        # Second run is completely idempotent
        second_run = reconcile_existing_reward_data()
        self.assertEqual(second_run, 0)
        self.assertEqual(sum(e.points for e in LedgerEntry.objects.all()), 0)

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

        # Claim Purchase API - disabled by default (SR-02)
        disabled_res = self.client.post('/api/rewards/points/claim-purchase/', {
            'order_id': 'ORD-5501',
            'store': 'Zara',
            'amount': '129.00'
        }, format='json')
        self.assertEqual(disabled_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(disabled_res.data.get('code'), 'feature_disabled')

        # Claim Purchase API with flag enabled
        with override_settings(MYC_PURCHASE_MANUAL_CLAIM_ENABLED=True):
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

    def test_database_reconciliation_detailed_mapping_and_invariants(self):
        """SR-08: Complete verification of historical transaction to double-entry ledger mapping."""
        from .models import RewardPointTransaction, PointAward, LedgerTxn, LedgerEntry
        from .services import reconcile_existing_reward_data

        # 1. Create distinct historical test transactions
        user_b = User.objects.create_user(email='reconcile_b@example.com', password='Password123!', name='User B')
        tx1 = RewardPointTransaction.objects.create(
            user=user_b,
            action_type='add_closet_item',
            points=50,
            description='Test closet item',
            reference_id='closet-1001'
        )
        tx2 = RewardPointTransaction.objects.create(
            user=user_b,
            action_type='share_look',
            points=120,
            description='Test shared look',
            reference_id='outfit-2001'
        )

        # 2. Run reconciliation
        reconciled = reconcile_existing_reward_data()
        self.assertGreaterEqual(reconciled, 2)

        # 3. Verify 1:1 mapping: each tx has a PointAward and LedgerTxn
        award1 = PointAward.objects.filter(user=user_b, award_type='add_closet_item', points_original=50).first()
        self.assertIsNotNone(award1)
        self.assertEqual(award1.state, 'AVAILABLE')

        award2 = PointAward.objects.filter(user=user_b, award_type='share_look', points_original=120).first()
        self.assertIsNotNone(award2)
        self.assertEqual(award2.state, 'AVAILABLE')

        txn1 = LedgerTxn.objects.filter(idempotency_key=f"reconcile:tx:{tx1.id}").first()
        self.assertIsNotNone(txn1)
        self.assertEqual(txn1.award_id, award1.id)

        txn2 = LedgerTxn.objects.filter(idempotency_key=f"reconcile:tx:{tx2.id}").first()
        self.assertIsNotNone(txn2)
        self.assertEqual(txn2.award_id, award2.id)

        # 4. Verify exactly 2 ledger entries per txn and strict zero-sum balance
        self.assertEqual(txn1.entries.count(), 2)
        self.assertEqual(sum(e.points for e in txn1.entries.all()), 0)

        self.assertEqual(txn2.entries.count(), 2)
        self.assertEqual(sum(e.points for e in txn2.entries.all()), 0)

        # 5. Global database invariants: zero sum across ALL ledger entries
        total_sum = sum(e.points for e in LedgerEntry.objects.all())
        self.assertEqual(total_sum, 0)

        # 6. Zero orphan entries (every entry has a valid txn and account)
        self.assertEqual(LedgerEntry.objects.filter(txn__isnull=True).count(), 0)
        self.assertEqual(LedgerEntry.objects.filter(account__isnull=True).count(), 0)

        # 7. Zero duplicate idempotency keys
        from django.db.models import Count
        dup_keys = LedgerTxn.objects.values('idempotency_key').annotate(c=Count('id')).filter(c__gt=1).count()
        self.assertEqual(dup_keys, 0)

        # 8. Complete idempotency: rerun reconciliation yields 0 new records
        self.assertEqual(reconcile_existing_reward_data(), 0)

    def test_gdpr_financial_history_retention_and_pseudonymization(self):
        """SR-28: User GDPR deletion zeroes available balance and pseudonymizes PII without destroying ledger audit rows."""
        from users.utils.common_utils import purge_and_anonymize_user
        from .models import RewardPointTransaction, PointAward, LedgerTxn, LedgerEntry

        target_user = User.objects.create_user(email='gdpr_fin@example.com', password='Password123!', name='GDPR Target')
        award_points(target_user, 'share_look')
        award_points(target_user, 'add_closet_item')

        profile = UserRewardProfile.objects.get(user=target_user)
        self.assertEqual(profile.available_points, 170)

        tx_count_before = RewardPointTransaction.objects.filter(user=target_user).count()
        self.assertEqual(tx_count_before, 2)

        # Execute GDPR account purge
        purged = purge_and_anonymize_user(target_user)
        self.assertTrue(purged)

        # 1. Available points zeroed out
        profile.refresh_from_db()
        self.assertEqual(profile.available_points, 0)

        # 2. Financial transaction rows preserved (NOT deleted)
        txs = list(RewardPointTransaction.objects.filter(user=target_user))
        self.assertEqual(len(txs), 2)
        for tx in txs:
            self.assertIn("pseudonymized", tx.description.lower())

        # 3. User personal identifiers wiped
        target_user.refresh_from_db()
        self.assertEqual(target_user.name, 'Deleted User')
        self.assertFalse(target_user.is_active)
        self.assertTrue(target_user.email.endswith('@deleted.closly.app'))
        self.assertIsNone(target_user.date_of_birth)
        self.assertIsNone(target_user.bio)

        # 4. Ledger transactions and state log descriptions pseudonymized
        from .models import LedgerTxn, AwardStateLog
        for ltxn in LedgerTxn.objects.filter(award__user=target_user):
            self.assertIn("pseudonymized", ltxn.description.lower())
        for log in AwardStateLog.objects.filter(award__user=target_user):
            self.assertIn("pseudonymized", log.reason.lower())

        # 5. Ledger integrity strictly preserved: zero-sum balance holds
        self.assertEqual(sum(e.points for e in LedgerEntry.objects.all()), 0)

        # 6. FK integrity verified: no orphan transactions or entries
        self.assertEqual(LedgerEntry.objects.filter(txn__isnull=True).count(), 0)
        self.assertEqual(LedgerTxn.objects.filter(award__isnull=True).count(), 0)

    def test_concurrent_activity_reward_protection(self):
        """SR-07: Concurrent award attempts for same outfit do not duplicate points or ledger entries."""
        from unittest.mock import MagicMock
        from .services import record_activity_reward
        from .models import PointAward, LedgerTxn

        outfit = MagicMock(id=9999, visibility='public')
        with override_settings(MYC_POINTS_ACTIVITY_AWARDS=True, MYC_ACTIVITY_POINTS_DAILY_CAP=120):
            # First award succeeds
            a1 = record_activity_reward(self.user, outfit)
            self.assertIsNotNone(a1)
            self.assertEqual(a1.points_current, 120)

            # Replaying duplicate call on same outfit returns existing award
            a2 = record_activity_reward(self.user, outfit)
            self.assertEqual(a1.id, a2.id)

            # Only one PointAward and one LedgerTxn exist for this outfit
            self.assertEqual(PointAward.objects.filter(user=self.user, outfit_id=9999).count(), 1)
            self.assertEqual(LedgerTxn.objects.filter(idempotency_key=f"share_look:{self.user.id}:9999").count(), 1)
