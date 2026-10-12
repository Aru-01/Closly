
from django.test import TestCase, override_settings
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
        self.assertTrue(response.data['data']['user']['is_online'])
        self.assertIn('last_seen', response.data['data']['user'])

    def test_preferences_dress_for_get_and_post(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('users:preferences')
        
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
        self.assertIsNotNone(user.otp)

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

    def test_user_activity_middleware(self):
        from users.middleware import UserActivityMiddleware
        from django.test import RequestFactory
        from django.http import HttpResponse

        factory = RequestFactory()
        request = factory.get('/api/users/profile/')
        request.user = self.user

        middleware = UserActivityMiddleware(get_response=lambda r: HttpResponse("OK"))
        response = middleware.process_response(request, HttpResponse("OK"))
        self.assertEqual(response.status_code, 200)

    def test_closet_points_and_gamification_tiers(self):
        from rewards.services import award_points
        from rewards.models import UserRewardProfile

        self.client.force_authenticate(user=self.user)

        # 1. Award share_look (+120)
        t1 = award_points(self.user, 'share_look')
        self.assertEqual(t1.points, 120)

        # 2. Award add_closet_item (+50)
        t2 = award_points(self.user, 'add_closet_item')
        self.assertEqual(t2.points, 50)

        # 3. Check summary via API
        points_res = self.client.get(reverse('rewards:points-summary'))
        self.assertEqual(points_res.status_code, status.HTTP_200_OK)
        data = points_res.data['data']
        self.assertEqual(data['total_points'], 170)
        self.assertEqual(data['current_tier'], 'Bronze')
        self.assertEqual(data['next_tier'], 'Silver')
        self.assertEqual(data['points_to_next_tier'], 1830)

        # 4. Check history via API
        history_res = self.client.get(reverse('rewards:points-history'))
        self.assertEqual(history_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history_res.data['data']), 2)

        # 5. Claim purchase points (+200)
        with override_settings(MYC_PURCHASE_MANUAL_CLAIM_ENABLED=True):
            claim_res = self.client.post(reverse('rewards:claim-purchase'), {
                'order_id': 'ORDER-99182',
                'store': 'H&M',
                'amount': '85.50'
            }, format='json')
            self.assertEqual(claim_res.status_code, status.HTTP_200_OK)
            self.assertEqual(claim_res.data['data']['points_awarded'], 200)

            # Duplicate claim should be rejected
            dup_res = self.client.post(reverse('rewards:claim-purchase'), {
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

        # Points are securely awarded once the invited friend verifies email (prevents unverified referral exploitation)
        friend = User.objects.get(email='friend@example.com')
        self.assertEqual(friend.referred_by, self.user)
        verify_url = reverse('users:verify-otp')
        v_res = self.client.post(verify_url, {'email': friend.email, 'otp': friend.otp}, format='json')
        self.assertEqual(v_res.status_code, status.HTTP_200_OK)

        # User 1 should have received +200 points for inviting a verified friend
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

        # 2. Public web landing page (UUID only, referral code stripped to prevent scraping)
        landing_url = f'/u/{self.user.id}/'
        landing_res = self.client.get(landing_url)
        self.assertEqual(landing_res.status_code, status.HTTP_200_OK)
        self.assertContains(landing_res, self.user.name)
        self.assertNotContains(landing_res, "referral-box")

    def test_password_reset_flow(self):
        # 1. Request Password Reset OTP
        reset_req_url = reverse('users:password-reset')
        res = self.client.post(reset_req_url, {'email': self.user.email}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])

        # Reload user from DB to get generated 6-digit OTP
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.otp)
        self.assertEqual(len(self.user.otp), 6)
        self.assertIsNotNone(self.user.otp_created_at)

        # 2. Verify OTP and obtain single-use reset_token
        verify_otp_url = reverse('users:password-reset-otp-verify')
        verify_res = self.client.post(verify_otp_url, {'email': self.user.email, 'otp': self.user.otp}, format='json')
        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_res.data['success'])
        reset_token = verify_res.data['data']['reset_token']
        self.assertTrue(bool(reset_token))

        # 3. Confirm New Password using reset_token
        confirm_url = reverse('users:password-reset-confirm')
        confirm_res = self.client.post(confirm_url, {
            'email': self.user.email,
            'reset_token': reset_token,
            'password': 'BrandNewSecurePass123!',
            'confirm_password': 'BrandNewSecurePass123!'
        }, format='json')
        self.assertEqual(confirm_res.status_code, status.HTTP_200_OK)
        self.assertTrue(confirm_res.data['success'])

        # 4. Verify login works with new password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewSecurePass123!'))

    def test_token_refresh_flow_and_deleted_user_handled_cleanly(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        # 1. Valid token refresh
        refresh = RefreshToken.for_user(self.user)
        refresh_url = reverse('users:token-refresh')
        res = self.client.post(refresh_url, {'refresh': str(refresh)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIn('access', res.data['data'])

        # 2. Token with deleted / non-existent user ID should return 401 Unauthorized, never 500
        fake_refresh = RefreshToken()
        fake_refresh['user_id'] = 999999
        res_fake = self.client.post(refresh_url, {'refresh': str(fake_refresh)}, format='json')
        self.assertEqual(res_fake.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(res_fake.data['success'])

    def test_self_profile_includes_counts_and_style_dna(self):
        """Test GET /api/users/profile/ includes followers, following, looks, closet counts and style_dna."""
        pref, _ = UserPreference.objects.get_or_create(user=self.user)
        pref.style_match = ['minimalist', 'nordic', 'streetwear']
        pref.save()

        self.client.force_authenticate(user=self.user)
        url = reverse('users:profile')
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        data = res.data['data']

        # Verify all requested fields exist
        self.assertIn('followers_count', data)
        self.assertIn('following_count', data)
        self.assertIn('looks_count', data)
        self.assertIn('outfit_count', data)
        self.assertIn('closet_count', data)
        self.assertIn('style_dna', data)
        self.assertIn('style_match', data)
        self.assertIn('current_tier', data)
        self.assertIn('is_online', data)
        self.assertTrue(data['is_online'])
        self.assertIn('last_seen', data)

        # Verify style_dna content
        self.assertEqual(data['style_dna'], ['minimalist', 'nordic', 'streetwear'])
        self.assertEqual(data['style_match'], ['minimalist', 'nordic', 'streetwear'])
        self.assertIsInstance(data['followers_count'], int)
        self.assertIsInstance(data['following_count'], int)
        self.assertIsInstance(data['looks_count'], int)
        self.assertIsInstance(data['closet_count'], int)

    def test_otp_verify_2min_rate_limiting(self):
        from django.core.cache import cache
        cache.clear()

        url = reverse('users:verify-otp')
        # OTP verification rate limit is 5 per 2 minutes (120s)
        for _ in range(5):
            res = self.client.post(url, {'email': 'throttle@example.com', 'otp': '0000'})
            self.assertNotEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # 6th attempt within the 2-minute window must return 429 Too Many Requests
        throttled_res = self.client.post(url, {'email': 'throttle@example.com', 'otp': '0000'})
        self.assertEqual(throttled_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(throttled_res.data['success'])


################################################################################
# EMAIL AND DEV CONFIG TESTS
################################################################################
"""
Automated tests for AWS SES SMTP email settings, runtime development isolation,
and network configuration safety.
Credentials and secrets are strictly verified for presence without logging or hardcoding.
"""

import socket
from django.test import TestCase
from django.conf import settings


class EmailAndDevConfigTestCase(TestCase):
    def test_email_backend_and_settings(self):
        """Verify standard Django email configuration adheres to AWS SES SMTP requirements."""
        from decouple import config
        configured_backend = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
        self.assertEqual(configured_backend, "django.core.mail.backends.smtp.EmailBackend")
        self.assertIn("amazonaws.com", settings.EMAIL_HOST)
        self.assertEqual(settings.EMAIL_PORT, 587)
        self.assertTrue(settings.EMAIL_USE_TLS)
        self.assertEqual(settings.DEFAULT_FROM_EMAIL, "noreply@myclosly.com")
        self.assertEqual(settings.SERVER_EMAIL, "noreply@myclosly.com")
        self.assertEqual(settings.EMAIL_TIMEOUT, 10)

    def test_email_credentials_configured_safely(self):
        """Verify email credential variables are loaded as strings without exposing values."""
        user_val = getattr(settings, "EMAIL_HOST_USER", None)
        pass_val = getattr(settings, "EMAIL_HOST_PASSWORD", None)
        self.assertIsNotNone(user_val)
        self.assertIsNotNone(pass_val)
        self.assertIsInstance(user_val, str)
        self.assertIsInstance(pass_val, str)

    def test_dev_environment_security_isolation(self):
        """Verify that development/test environments do not poison browsers with HSTS or HTTPS loops."""
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertEqual(getattr(settings, "SECURE_HSTS_SECONDS", 0), 0)
        self.assertFalse(getattr(settings, "SESSION_COOKIE_SECURE", True))
        self.assertFalse(getattr(settings, "CSRF_COOKIE_SECURE", True))
        self.assertIn("http://127.0.0.1:8000", settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn("http://localhost:8000", settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn("http://127.0.0.1:8001", settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn("http://localhost:8001", settings.CSRF_TRUSTED_ORIGINS)

    def test_aws_ses_smtp_dns_and_socket(self):
        """Verify network reachability of AWS SES SMTP eu-central-1 endpoint."""
        target_host = "email-smtp.eu-central-1.amazonaws.com"
        target_port = 587
        try:
            ip = socket.gethostbyname(target_host)
            self.assertTrue(bool(ip))
            sock = socket.create_connection((target_host, target_port), timeout=5)
            banner = sock.recv(1024).decode("utf-8", errors="ignore")
            sock.close()
            self.assertTrue(banner.startswith("220") or "SimpleEmailService" in banner)
        except (socket.gaierror, socket.timeout, ConnectionRefusedError) as e:
            self.fail(f"AWS SES SMTP endpoint unreachable: {e}")


################################################################################
# GAP FEATURES TESTS
################################################################################
import io
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from users.models import Device
from closet.models import ClosetItem
from closet.services.safety_services import evaluate_image_safety, NsfwContentDetectedError
from rewards.models import LedgerAccount, LedgerTransaction, LedgerTxn, LedgerEntry
from rewards.services import create_balanced_ledger_txn, LedgerImbalanceError, calculate_account_balance
from users.services.gdpr_services import purge_and_anonymize_user

User = get_user_model()


class MissingFeaturesComprehensiveTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='gap_user@example.com',
            password='Password123!',
            name='Gap Auditor',
            is_active=True,
            is_email_verified=True,
            auth_provider='apple'
        )
        self.client.force_authenticate(user=self.user)

    # =========================================================================
    # FEATURE 1: Device Push Token Registration (APNs / FCM)
    # =========================================================================
    def test_device_registration_apns_and_fcm(self):
        # 1. Register Apple APNs token
        payload_apns = {
            "apns_token": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
            "platform": "ios",
            "prefs": {"sound": True, "badge": True}
        }
        resp = self.client.post("/v1/devices", payload_apns, format="json")
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        self.assertTrue(resp.data.get("success"))
        device = Device.objects.filter(user=self.user, platform="ios").first()
        self.assertIsNotNone(device)
        self.assertEqual(device.token, payload_apns["apns_token"])

        # 2. Register / Update with Google FCM token
        payload_fcm = {
            "fcm_token": "fcm_reg_token_example_1234567890_abcdef",
            "platform": "android",
            "prefs": {"sound": False}
        }
        resp2 = self.client.post("/v1/devices", payload_fcm, format="json")
        self.assertIn(resp2.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        device_android = Device.objects.filter(user=self.user, platform="android").first()
        self.assertIsNotNone(device_android)
        self.assertEqual(device_android.token, payload_fcm["fcm_token"])

    # =========================================================================
    # FEATURE 2: GDPR Data Export (Article 20 Compliance) - GET /v1/me/export -> 202
    # =========================================================================
    @patch('users.tasks.export_user_data_task.delay')
    def test_gdpr_data_export_async_endpoint(self, mock_delay):
        resp = self.client.get("/v1/me/export")
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(resp.data.get("success"))
        self.assertEqual(resp.data.get("data", {}).get("status"), "processing")
        mock_delay.assert_called_once_with(str(self.user.id))

    # =========================================================================
    # FEATURE 3: GDPR Erasure Cascade (Storage Deletion & Apple Revocation)
    # =========================================================================
    @patch('requests.post')
    def test_gdpr_erasure_cascade_s3_and_apple_revocation(self, mock_post):
        # Mock Apple OAuth revocation response
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        # Create a closet item with an actual storage file
        dummy_file = SimpleUploadedFile("jacket.jpg", b"fake_jpeg_content", content_type="image/jpeg")
        item = ClosetItem.objects.create(
            user=self.user,
            name="Winter Jacket",
            image=dummy_file
        )
        stored_path = item.image.name
        self.assertTrue(default_storage.exists(stored_path))

        # Perform GDPR Purge & Anonymization
        success = purge_and_anonymize_user(self.user)
        self.assertTrue(success)

        # 1. Image physically deleted from default_storage
        self.assertFalse(default_storage.exists(stored_path))

        # 2. Apple Revocation HTTP POST called
        mock_post.assert_called()
        apple_call_found = any(
            "appleid.apple.com/auth/revoke" in str(call_args)
            for call_args in mock_post.call_args_list
        )
        self.assertTrue(apple_call_found)

        # 3. User anonymized
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Deleted User")
        self.assertFalse(self.user.is_active)
        self.assertIsNone(self.user.bio)

    # =========================================================================
    # FEATURE 4: NSFW Pre-Screening Filter
    # =========================================================================
    def test_nsfw_pre_screening_filter(self):
        # Clean image passes pre-screening
        clean_file = SimpleUploadedFile("clean_shirt.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 200, content_type="image/jpeg")
        clean_item = ClosetItem.objects.create(
            user=self.user,
            name="White Oxford",
            image=clean_file
        )
        clean_path = clean_item.image.name
        self.assertTrue(default_storage.exists(clean_path))

        passed = evaluate_image_safety(clean_item.image, fail_closed=False)
        self.assertTrue(passed)
        self.assertTrue(default_storage.exists(clean_path))

        # Explicit / NSFW image triggers failure and physical deletion
        with patch('closet.services.safety_services.check_image_safety', return_value=(False, 'explicit_content', 0.98)):
            bad_file = SimpleUploadedFile("explicit_pic.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 200, content_type="image/jpeg")
            bad_item = ClosetItem.objects.create(
                user=self.user,
                name="Flagged Item",
                image=bad_file
            )
            bad_path = bad_item.image.name
            self.assertTrue(default_storage.exists(bad_path))

            with self.assertRaises(NsfwContentDetectedError):
                evaluate_image_safety(bad_item.image, fail_closed=True)

            # Image MUST be immediately deleted from storage
            self.assertFalse(default_storage.exists(bad_path))

    # =========================================================================
    # FEATURE 5: Strict Double-Entry Financial Ledger
    # =========================================================================
    def test_double_entry_financial_ledger_integrity(self):
        # 1. Accounts
        user_acct = LedgerAccount.get_or_create_user_account(self.user)
        system_reserve = LedgerAccount.get_system_reserve_account()

        # 2. Balanced transaction: User gets 500 points (Credit), System Reserve decreases by 500 (Debit)
        entries = [
            {"account": user_acct, "entry_type": "credit", "amount": 500},
            {"account": system_reserve, "entry_type": "debit", "amount": 500},
        ]
        txn = create_balanced_ledger_txn(
            description="Milestone Reward #1",
            entries=entries,
            reference_id="TEST-TXN-01"
        )
        self.assertIsNotNone(txn)
        self.assertEqual(txn.entries.count(), 2)

        # Mathematical verification: sum of debits (-500) + sum of credits (+500) = 0
        self.assertEqual(sum(e.points for e in txn.entries.all()), 0)

        # Derive balance strictly from immutable ledger
        user_bal = calculate_account_balance(user_acct)
        self.assertEqual(user_bal, 500)

        # 3. Imbalance protection: unbalance must raise LedgerImbalanceError
        unbalanced_entries = [
            {"account": user_acct, "entry_type": "credit", "amount": 300},
            {"account": system_reserve, "entry_type": "debit", "amount": 200},  # Net +100 imbalance
        ]
        with self.assertRaises(LedgerImbalanceError):
            create_balanced_ledger_txn(
                description="Hacked Transaction",
                entries=unbalanced_entries
            )


################################################################################
# SECURITY AUDIT TESTS
################################################################################
from datetime import date, timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import (
    AccountDeletionRequest,
    Invite,
    Consent,
    DeletionJob,
    GdprAction,
    Device,
)
from rewards.models import RewardPointTransaction, UserRewardProfile
from users.throttling import record_failed_attempt, check_lockout, clear_failed_attempts
from users.utils.auth_utils import revoke_all_user_tokens

User = get_user_model()


class SecurityAuditTestCase(TestCase):
    """
    Comprehensive Security Audit Test Suite covering fixes from 01_users_auth_gdpr.md.
    """

    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.user_password = "SecurePassword123!"
        self.user = User.objects.create_user(
            email="victim@example.com",
            password=self.user_password,
            name="Victim User",
            date_of_birth=date(1995, 6, 15),
            is_active=True,
            is_email_verified=True,
        )

    def tearDown(self):
        cache.clear()

    # =========================================================================
    # U-01: Rate Limiting & Account Lockout
    # =========================================================================

    def test_reverse_proxy_ip_spoofing_does_not_bypass_throttling(self):
        """
        Verify that an attacker appending random IPs to X-Forwarded-For cannot bypass
        rate limiting. DRF with NUM_PROXIES=1 and get_client_ip picks the untrusted hop.
        """
        url = reverse("users:verify-otp")
        email = "spoof_throttle@example.com"
        User.objects.create_user(
            email=email,
            password=self.user_password,
            name="Spoof Test",
            date_of_birth=date(1998, 1, 1),
            is_email_verified=False,
        )

        # Send 5 requests with spoofed XFF headers: attacker changes the first IP
        for i in range(5):
            spoofed_xff = f"198.51.100.{i}, 203.0.113.50"
            resp = self.client.post(
                url,
                {"email": email, "otp": "999999"},
                format="json",
                HTTP_X_FORWARDED_FOR=spoofed_xff,
                REMOTE_ADDR="127.0.0.1",
            )
            self.assertNotEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # 6th request from the same proxy client IP (203.0.113.50) must be throttled
        resp_throttled = self.client.post(
            url,
            {"email": email, "otp": "999999"},
            format="json",
            HTTP_X_FORWARDED_FOR="198.51.100.99, 203.0.113.50",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(resp_throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_otp_failed_attempts_triggers_15_minute_lockout(self):
        """
        Verify that 5 failed attempts trigger a 15-minute account lockout (check_lockout).
        """
        identifier = "lockout_test@example.com"
        scope = "otp_verify"

        # Record 4 failed attempts - should not be locked
        for _ in range(4):
            record_failed_attempt(identifier, scope)
        self.assertFalse(check_lockout(identifier, scope))

        # 5th failed attempt triggers lockout
        record_failed_attempt(identifier, scope)
        self.assertTrue(check_lockout(identifier, scope))

        # Clearing failed attempts resets lockout
        clear_failed_attempts(identifier, scope)
        self.assertFalse(check_lockout(identifier, scope))

    # =========================================================================
    # U-02 & U-31: Firebase Authentication Hardening
    # =========================================================================

    @patch("users.views.auth_views.verify_firebase_token")
    def test_firebase_login_rejects_unverified_email(self, mock_verify):
        """
        Firebase login must reject ID tokens where email_verified is False.
        """
        mock_verify.return_value = {
            "uid": "fb_uid_123",
            "email": "unverified_fb@example.com",
            "email_verified": False,
            "firebase": {"sign_in_provider": "google.com"},
        }
        url = reverse("users:firebase-auth")
        resp = self.client.post(url, {"id_token": "valid_token_unverified"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verified", resp.data["message"].lower())

    @patch("users.views.auth_views.verify_firebase_token")
    def test_firebase_login_rejects_unapproved_providers(self, mock_verify):
        """
        Firebase login must reject unsupported providers (e.g. password or anonymous).
        """
        mock_verify.return_value = {
            "uid": "fb_uid_456",
            "email": "anon_fb@example.com",
            "email_verified": True,
            "firebase": {"sign_in_provider": "anonymous"},
        }
        url = reverse("users:firebase-auth")
        resp = self.client.post(url, {"id_token": "token_from_anonymous"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unsupported", resp.data["message"].lower())

    @patch("users.views.auth_views.verify_firebase_token")
    def test_firebase_login_ignores_client_supplied_email_and_avatar(self, mock_verify):
        """
        Server must ignore spoofed client email/avatar in payload and exclusively use token claims.
        """
        mock_verify.return_value = {
            "uid": "fb_google_789",
            "email": "real_google_user@gmail.com",
            "email_verified": True,
            "name": "Google User",
            "picture": None,
            "firebase": {"sign_in_provider": "google.com"},
        }
        url = reverse("users:firebase-auth")
        # Attacker tries to inject victim's email in the body
        resp = self.client.post(
            url,
            {
                "id_token": "valid_token",
                "email": "victim@example.com",
                "photo_url": "http://169.254.169.254/latest/meta-data/",
                "date_of_birth": "2000-01-01",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Account created or logged in MUST be real_google_user@gmail.com, not victim@example.com
        created_user = User.objects.get(email="real_google_user@gmail.com")
        self.assertIsNotNone(created_user)
        self.assertNotEqual(created_user.email, "victim@example.com")

    # =========================================================================
    # U-10: Age Gate (16+)
    # =========================================================================

    def test_signup_rejects_under_16(self):
        """Users under 16 years of age cannot register."""
        underage_dob = (timezone.now().date() - timedelta(days=365 * 14)).isoformat()
        url = reverse("users:signup")
        data = {
            "name": "Underage User",
            "email": "underage@example.com",
            "date_of_birth": underage_dob,
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }
        resp = self.client.post(url, data, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", resp.data["errors"])

    def test_age_gate_cross_path_enforcement(self):
        """SR-21 & U-10: Strict boundary enforcement across signup and profile update (15 rejected, 16 accepted, 17+ accepted, missing rejected)."""
        today = timezone.now().date()
        dob_15 = (today.replace(year=today.year - 15)).isoformat()
        dob_16 = (today.replace(year=today.year - 16)).isoformat()
        dob_17 = (today.replace(year=today.year - 17)).isoformat()
        url = reverse("users:signup")

        # 1. Age 15 is rejected
        resp_15 = self.client.post(url, {
            "name": "Fifteen User",
            "email": "fifteen@example.com",
            "date_of_birth": dob_15,
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }, format="json")
        self.assertEqual(resp_15.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Missing DOB is rejected
        resp_missing = self.client.post(url, {
            "name": "Missing DOB User",
            "email": "missing_dob@example.com",
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }, format="json")
        self.assertEqual(resp_missing.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Exactly age 16 is accepted
        resp_16 = self.client.post(url, {
            "name": "Sixteen User",
            "email": "sixteen@example.com",
            "date_of_birth": dob_16,
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }, format="json")
        self.assertEqual(resp_16.status_code, status.HTTP_201_CREATED)

        # 4. Age 17 is accepted
        resp_17 = self.client.post(url, {
            "name": "Seventeen User",
            "email": "seventeen@example.com",
            "date_of_birth": dob_17,
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }, format="json")
        self.assertEqual(resp_17.status_code, status.HTTP_201_CREATED)

        # 5. Profile update bypass attempt with underage DOB is rejected
        self.client.force_authenticate(user=self.user)
        update_url = reverse("users:profile")
        resp_update_bypass = self.client.patch(update_url, {
            "date_of_birth": dob_15
        }, format="json")
        self.assertEqual(resp_update_bypass.status_code, status.HTTP_400_BAD_REQUEST)

        # 5. Firebase social login without DOB for new user is rejected (U-10 / Task 1.2)
        self.client.force_authenticate(user=None)
        with patch('users.views.auth_views.verify_firebase_token') as mock_verify:
            mock_verify.return_value = {
                'uid': 'firebase_no_dob_uid_123',
                'email': 'no_dob_social@example.com',
                'email_verified': True,
                'name': 'No DOB Social',
                'firebase': {'sign_in_provider': 'google.com'}
            }
            fb_url = reverse("users:firebase-auth")
            resp_fb_no_dob = self.client.post(fb_url, {
                "firebase_token": "valid_token_mock_nodob",
            }, format="json")
            self.assertEqual(resp_fb_no_dob.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(resp_fb_no_dob.data.get("code"), "DOB_REQUIRED")

        # 6. Firebase social login with underage DOB is rejected (SR-21 / U-10)
        with patch('users.views.auth_views.verify_firebase_token') as mock_verify:
            mock_verify.return_value = {
                'uid': 'firebase_underage_uid_123',
                'email': 'underage_social@example.com',
                'email_verified': True,
                'name': 'Underage Social',
                'firebase': {'sign_in_provider': 'google.com'}
            }
            fb_url = reverse("users:firebase-auth")
            resp_fb_underage = self.client.post(fb_url, {
                "firebase_token": "valid_token_mock",
                "date_of_birth": dob_15
            }, format="json")
            self.assertEqual(resp_fb_underage.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(resp_fb_underage.data.get("code"), "UNDERAGE")

            # 7. Firebase social login with 16+ DOB is accepted
            mock_verify.return_value = {
                'uid': 'firebase_valid_uid_123',
                'email': 'valid_social@example.com',
                'email_verified': True,
                'name': 'Valid Social',
                'firebase': {'sign_in_provider': 'google.com'}
            }
            resp_fb_valid = self.client.post(fb_url, {
                "firebase_token": "valid_token_mock_2",
                "date_of_birth": dob_16
            }, format="json")
            self.assertEqual(resp_fb_valid.status_code, status.HTTP_200_OK)

    # =========================================================================
    # U-11: Unicode Name Validation
    # =========================================================================

    def test_unicode_names_allowed_and_xss_rejected(self):
        """Ensure names with diacritics/accents pass, but script tags fail."""
        url = reverse("users:signup")
        dob = "1995-01-01"

        # Valid Unicode names
        for valid_name in ["Renée Müller", "José-María O'Connor", "Björn Håkon"]:
            email = f"user_{abs(hash(valid_name))}@example.com"
            data = {
                "name": valid_name,
                "email": email,
                "date_of_birth": dob,
                "gender": "male",
                "password": "ValidPassword123!",
                "confirm_password": "ValidPassword123!",
            }
            resp = self.client.post(url, data, format="json")
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, f"Failed for valid name: {valid_name}")

        # Invalid XSS name
        xss_data = {
            "name": "<script>alert(1)</script>",
            "email": "xss@example.com",
            "date_of_birth": dob,
            "gender": "male",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }
        resp = self.client.post(url, xss_data, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", resp.data["errors"])

    # =========================================================================
    # U-16: Secure Password Reset Flow with Cryptographic Reset Token
    # =========================================================================

    def test_password_reset_confirm_requires_valid_reset_token(self):
        """
        Password reset confirm requires the single-use reset_token issued by OTP verify.
        An attacker without the token cannot reset the victim's password.
        """
        confirm_url = reverse("users:password-reset-confirm")

        # 1. Attempt reset without reset_token
        resp = self.client.post(
            confirm_url,
            {
                "email": self.user.email,
                "password": "HackedPassword123!",
                "confirm_password": "HackedPassword123!",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Legitimate flow: generate OTP
        self.client.post(reverse("users:password-reset"), {"email": self.user.email}, format="json")
        self.user.refresh_from_db()

        # 3. Verify OTP -> get reset_token
        v_resp = self.client.post(
            reverse("users:password-reset-otp-verify"),
            {"email": self.user.email, "otp": self.user.otp},
            format="json",
        )
        self.assertEqual(v_resp.status_code, status.HTTP_200_OK)
        reset_token = v_resp.data["data"]["reset_token"]
        self.assertTrue(bool(reset_token))

        # 4. Confirm reset with reset_token
        c_resp = self.client.post(
            confirm_url,
            {
                "email": self.user.email,
                "reset_token": reset_token,
                "password": "NewLegitPassword123!",
                "confirm_password": "NewLegitPassword123!",
            },
            format="json",
        )
        self.assertEqual(c_resp.status_code, status.HTTP_200_OK)

        # 5. Token is single-use: replay attempt must be rejected
        replay_resp = self.client.post(
            confirm_url,
            {
                "email": self.user.email,
                "reset_token": reset_token,
                "password": "ReplayPassword123!",
                "confirm_password": "ReplayPassword123!",
            },
            format="json",
        )
        self.assertEqual(replay_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_and_reset_revokes_all_jwt_tokens(self):
        """
        Verify that changing password revokes all outstanding JWT tokens for that user.
        """
        refresh = RefreshToken.for_user(self.user)

        # Revoke tokens via helper
        count = revoke_all_user_tokens(self.user)
        self.assertGreaterEqual(count, 0)

        # Authenticating with old token should now fail if refresh is attempted
        refresh_url = reverse("users:token-refresh")
        resp = self.client.post(refresh_url, {"refresh": str(refresh)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # =========================================================================
    # U-04: GDPR Deletion Security
    # =========================================================================

    def test_account_deletion_verification_get_does_not_delete_user(self):
        """
        GET /api/users/verify-account-deletion/<token>/ renders confirmation UI
        and MUST NOT delete the user (state-changing GET vulnerability fix).
        """
        del_req = AccountDeletionRequest.objects.create(
            user=self.user,
            email=self.user.email,
            verification_token="11111111-2222-3333-4444-555555555555",
            status="pending",
        )
        url = reverse("users:verify-account-deletion", kwargs={"token": str(del_req.verification_token)})

        # GET request
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # User MUST still exist
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        del_req.refresh_from_db()
        self.assertEqual(del_req.status, "pending")

    def test_account_deletion_verification_post_executes_deletion(self):
        """
        POST /api/users/verify-account-deletion/<token>/ executes deletion.
        """
        del_req = AccountDeletionRequest.objects.create(
            user=self.user,
            email=self.user.email,
            verification_token="22222222-3333-4444-5555-666666666666",
            status="pending",
        )
        url = reverse("users:verify-account-deletion", kwargs={"token": str(del_req.verification_token)})

        # POST request
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # User is anonymized and deactivated in database per GDPR Art. 17 / SR-28
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.name, 'Deleted User')
        self.assertTrue(self.user.email.startswith('deleted_'))
        del_req.refresh_from_db()
        self.assertEqual(del_req.status, "completed")

    def test_account_deletion_rejects_expired_token(self):
        """
        Tokens older than 24 hours must be rejected.
        """
        expired_req = AccountDeletionRequest.objects.create(
            user=self.user,
            email=self.user.email,
            verification_token="33333333-4444-5555-6666-777777777777",
            status="pending",
        )
        # Artificially age the creation date past 24 hours
        AccountDeletionRequest.objects.filter(pk=expired_req.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        expired_req.refresh_from_db()

        url = reverse("users:verify-account-deletion", kwargs={"token": str(expired_req.verification_token)})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # User is not deleted
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    # =========================================================================
    # U-18: Case-Insensitive Email Normalization & Uniqueness
    # =========================================================================

    def test_email_case_insensitivity_and_unique_constraint(self):
        """
        Attempting to register alice@example.com when Alice@Example.Com exists must fail.
        """
        url = reverse("users:signup")
        data1 = {
            "name": "Case User",
            "email": "CaseSensitive@Example.Com",
            "date_of_birth": "1995-05-05",
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }
        res1 = self.client.post(url, data1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Attempt to signup with lowercase
        data2 = {
            "name": "Case User Duplicate",
            "email": "casesensitive@example.com",
            "date_of_birth": "1995-05-05",
            "gender": "female",
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        }
        self.client.post(url, data2, format="json")
        # Should be rejected because email already registered (unverified or verified)
        # Note: if unverified, user is re-registered or updated, but duplicate DB record is never created.
        user_count = User.objects.filter(email__iexact="casesensitive@example.com").count()
        self.assertEqual(user_count, 1)

    # =========================================================================
    # U-19: Public Profile Sanitization
    # =========================================================================

    def test_public_profile_strictly_uuid_and_no_sensitive_data(self):
        """
        Public profile page only resolves valid UUIDs. Passing email handle or username returns 404.
        """
        # 1. Valid UUID lookup works
        valid_url = f"/u/{self.user.id}/"
        resp = self.client.get(valid_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertContains(resp, self.user.name)

        # Sensitive presence indicators and referral code must not be exposed
        self.assertNotContains(resp, "referral-box")
        self.assertNotContains(resp, "Online Now")

        # 2. Arbitrary handle/email enumeration attempt returns 404
        handle_url = "/u/victim/"
        resp2 = self.client.get(handle_url)
        self.assertEqual(resp2.status_code, status.HTTP_404_NOT_FOUND)

        email_url = f"/u/{self.user.email}/"
        resp3 = self.client.get(email_url)
        self.assertEqual(resp3.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # U-08: Invite-Gated Registration & Atomic Consumption
    # =========================================================================

    @override_settings(MYC_REGISTRATION_MODE="invite", MYC_INVITE_BYPASS_CODES="APPLE_REVIEW,TESTER_PASS")
    def test_invite_gated_registration_flow(self):
        signup_url = reverse("users:signup")
        base_data = {
            "name": "Invited User",
            "email": "invitee@example.com",
            "date_of_birth": "1998-04-12",
            "gender": "female",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
        }

        # 1. Missing invite code fails with INVITE_REQUIRED
        resp1 = self.client.post(signup_url, base_data, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp1.data.get("code"), "INVITE_REQUIRED")

        # 2. Invalid invite code fails with INVALID_INVITE
        invalid_data = {**base_data, "invite_code": "NONEXISTENT"}
        resp2 = self.client.post(signup_url, invalid_data, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp2.data.get("code"), "INVALID_INVITE")

        # 3. Bypass code succeeds without database Invite record
        bypass_data = {**base_data, "email": "reviewer@example.com", "invite_code": "APPLE_REVIEW"}
        resp3 = self.client.post(signup_url, bypass_data, format="json")
        self.assertEqual(resp3.status_code, status.HTTP_201_CREATED)

        # 4. Valid invite code succeeds and consumes invite atomically
        invite = Invite.objects.create(code="VIP_ALPHA_99", kind="early_access", owner_user=self.user)
        valid_data = {**base_data, "email": "realinvitee@example.com", "invite_code": "VIP_ALPHA_99"}
        resp4 = self.client.post(signup_url, valid_data, format="json")
        self.assertEqual(resp4.status_code, status.HTTP_201_CREATED)
        invite.refresh_from_db()
        self.assertIsNotNone(invite.used_by)
        self.assertIsNotNone(invite.used_at)
        self.assertEqual(invite.used_by.email, "realinvitee@example.com")

        # 5. Reusing the same consumed invite code fails
        reuse_data = {**base_data, "email": "second_invitee@example.com", "invite_code": "VIP_ALPHA_99"}
        resp5 = self.client.post(signup_url, reuse_data, format="json")
        self.assertEqual(resp5.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp5.data.get("code"), "INVALID_INVITE")

    # =========================================================================
    # U-09: Referral Reward Hardening (Pending -> Activation)
    # =========================================================================

    def test_referral_reward_pending_to_activation_flow(self):
        signup_url = reverse("users:signup")
        signup_data = {
            "name": "Referred Friend",
            "email": "friend_ref@example.com",
            "date_of_birth": "1996-07-20",
            "gender": "male",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
            "referral_code": self.user.referral_code,
        }
        resp = self.client.post(signup_url, signup_data, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        friend = User.objects.get(email="friend_ref@example.com")
        self.assertEqual(friend.referred_by, self.user)

        # 1. Referral reward is created with status='pending' and points NOT yet given
        pending_tx = RewardPointTransaction.objects.filter(
            user=self.user,
            action_type="invite_friend",
            status="pending"
        ).first()
        self.assertIsNotNone(pending_tx)
        self.assertEqual(pending_tx.reference_id, str(friend.id))

        referrer_profile = UserRewardProfile.objects.filter(user=self.user).first()
        initial_points = referrer_profile.available_points if referrer_profile else 0
        self.assertEqual(initial_points, 0)

        # 2. OTP verification activates the referral reward and awards points
        verify_url = reverse("users:verify-otp")
        verify_resp = self.client.post(verify_url, {"email": friend.email, "otp": friend.otp}, format="json")
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)

        pending_tx.refresh_from_db()
        self.assertEqual(pending_tx.status, "completed")

        referrer_profile = UserRewardProfile.objects.get(user=self.user)
        self.assertEqual(referrer_profile.available_points, 200)

        # 3. Duplicate activation attempt is idempotent and does not credit points again
        from rewards.services import activate_referral_reward
        result = activate_referral_reward(friend)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "completed")
        referrer_profile.refresh_from_db()
        self.assertEqual(referrer_profile.available_points, 200)

    # =========================================================================
    # Privacy Consent Recording
    # =========================================================================

    def test_consent_system_recording(self):
        signup_url = reverse("users:signup")
        signup_data = {
            "name": "Consent User",
            "email": "consent_user@example.com",
            "date_of_birth": "1994-01-15",
            "gender": "female",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
        }
        resp = self.client.post(signup_url, signup_data, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email="consent_user@example.com")
        # 1. Signup records tos_privacy consent
        tos_consent = Consent.objects.filter(user=user, kind="tos_privacy").first()
        self.assertIsNotNone(tos_consent)
        self.assertTrue(tos_consent.granted)
        self.assertIsNotNone(tos_consent.occurred_at)

        # 2. Device registration records push_notification consent
        self.client.force_authenticate(user=user)
        device_url = reverse("users:devices")
        dev_resp = self.client.post(device_url, {"apns_token": "a" * 64, "prefs": {"likes": True}}, format="json")
        self.assertIn(dev_resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

        device = Device.objects.filter(user=user, apns_token="a" * 64).first()
        self.assertIsNotNone(device)
        push_consent = Consent.objects.filter(user=user, kind="push_notification").first()
        self.assertIsNotNone(push_consent)
        self.assertTrue(push_consent.granted)

    # =========================================================================
    # U-04, U-15, U-27: GDPR Deletion Job Execution & Resumability
    # =========================================================================

    def test_gdpr_deletion_job_steps_and_resumability(self):
        victim = User.objects.create_user(
            email="to_be_deleted@example.com",
            password="SecurePassword123!",
            name="Delete Me",
            date_of_birth=date(1990, 1, 1),
            is_active=True,
            is_email_verified=True,
        )
        victim_id = victim.id

        from users.tasks import execute_gdpr_deletion_job

        # Create DeletionJob with step 1 already done (simulate partial run / resumption)
        job = DeletionJob.objects.create(
            user_id=victim_id,
            user_email=victim.email,
            status="running",
            steps_done=[1]
        )

        # Execute job
        result = execute_gdpr_deletion_job(str(job.id))
        self.assertTrue(result)

        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        self.assertIn(2, job.steps_done)
        self.assertIn(5, job.steps_done)
        self.assertIn(9, job.steps_done)
        self.assertIsNotNone(job.finished_at)
        # Confirm user was anonymized and PII purged (GDPR Art. 17 / SR-28)
        victim.refresh_from_db()
        self.assertFalse(victim.is_active)
        self.assertEqual(victim.name, 'Deleted User')
        self.assertTrue(victim.email.startswith('deleted_'))
        self.assertFalse(victim.has_usable_password())

    def test_account_deletion_re_request_creates_fresh_record(self):
        """U-27: Multiple deletion requests must produce distinct fresh records."""
        url = reverse("users:delete-account-request")
        payload = {"name": self.user.name, "email": self.user.email}

        resp1 = self.client.post(url, payload, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        req1 = AccountDeletionRequest.objects.filter(user=self.user).latest("created_at")

        resp2 = self.client.post(url, payload, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        req2 = AccountDeletionRequest.objects.filter(user=self.user).latest("created_at")

        self.assertNotEqual(req1.id, req2.id)
        self.assertNotEqual(req1.verification_token, req2.verification_token)

    # =========================================================================
    # GDPR Data Export
    # =========================================================================

    def test_gdpr_data_export_endpoint(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("users:gdpr-export")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get("success"))
        export_data = resp.data.get("data", {})
        self.assertEqual(export_data.get("user", {}).get("email"), self.user.email)
        self.assertIn("preferences", export_data)
        self.assertIn("consents", export_data)

        # Audit action logged
        action = GdprAction.objects.filter(user_id=self.user.id, action_type="data_export").first()
        self.assertIsNotNone(action)

    # =========================================================================
    # U-12: Anti-Enumeration Protections
    # =========================================================================

    def test_email_enumeration_protection_on_unauthenticated_endpoints(self):
        # 1. Resend OTP with non-existent email returns 200 with generic response
        resend_url = reverse("users:resend-otp")
        res_resp = self.client.post(resend_url, {"email": "nobody_exists@example.com"}, format="json")
        self.assertEqual(res_resp.status_code, status.HTTP_200_OK)

        # 2. Verify OTP with non-existent email returns generic 400
        verify_url = reverse("users:verify-otp")
        v_resp = self.client.post(verify_url, {"email": "nobody_exists@example.com", "otp": "999999"}, format="json")
        self.assertEqual(v_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(v_resp.data.get("code"), "INVALID_OTP")

        # 3. Password reset request with non-existent email returns 200 generic
        pwd_url = reverse("users:password-reset")
        p_resp = self.client.post(pwd_url, {"email": "nobody_exists@example.com"}, format="json")
        self.assertEqual(p_resp.status_code, status.HTTP_200_OK)

    # =========================================================================
    # U-13: Username Selection & Share Links
    # =========================================================================

    def test_username_selection_and_share_link(self):
        self.client.force_authenticate(user=self.user)
        profile_url = reverse("users:profile")

        # 1. Update username
        patch_resp = self.client.patch(profile_url, {"username": "fashionista_99"}, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "fashionista_99")

        # 2. Duplicate username rejected (case-insensitive)
        other_user = User.objects.create_user(
            email="other@example.com",
            password="SecurePassword123!",
            name="Other",
            date_of_birth=date(1992, 2, 2)
        )
        self.client.force_authenticate(user=other_user)
        dup_resp = self.client.patch(profile_url, {"username": "FASHIONISTA_99"}, format="json")
        self.assertEqual(dup_resp.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Share URL includes username
        self.client.force_authenticate(user=self.user)
        share_url = reverse("users:profile-share")
        share_resp = self.client.get(share_url)
        self.assertEqual(share_resp.status_code, status.HTTP_200_OK)
        self.assertIn("fashionista_99", share_resp.data.get("data", {}).get("share_url", ""))

        # 4. Public profile web view resolves username
        pub_resp = self.client.get("/u/fashionista_99/")
        self.assertEqual(pub_resp.status_code, status.HTTP_200_OK)
        self.assertContains(pub_resp, self.user.name)

    # =========================================================================
    # U-21: Onboarding Preferences & Cache Invalidation
    # =========================================================================

    def test_onboarding_preferences_and_feed_cache_invalidation(self):
        self.client.force_authenticate(user=self.user)
        pref_url = reverse("users:preferences")

        # Seed feed cache
        feed_cache_key = f"user_feed_{self.user.id}"
        cache.set(feed_cache_key, ["item_1", "item_2"], timeout=600)
        self.assertIsNotNone(cache.get(feed_cache_key))

        pref_payload = {
            "price_band": "premium",
            "gender_prefs": ["female", "unisex"],
            "clothing_sizes": ["M", "L"],
            "blocked_brands": ["FastFashionCorp"],
            "onboarding_completed": True
        }
        resp = self.client.patch(pref_url, pref_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Feed cache must be invalidated
        self.assertIsNone(cache.get(feed_cache_key))

        # Preferences persisted
        self.user.preferences.refresh_from_db()
        self.assertEqual(self.user.preferences.price_band, "premium")
        self.assertIn("female", self.user.preferences.gender_prefs)
        self.assertIn("fastfashioncorp", self.user.preferences.blocked_brands)

    # =========================================================================
    # U-25: Data Retention Tasks
    # =========================================================================

    def test_retention_cleanup_tasks(self):
        from users.models import UserLoginHistory
        from users.tasks import purge_old_login_history_task, purge_completed_gdpr_jobs_task

        # Create old login history (>90 days old)
        old_login = UserLoginHistory.objects.create(
            user=self.user,
            ip_address="192.168.1.0",
            auth_method="email",
        )
        UserLoginHistory.objects.filter(pk=old_login.pk).update(
            login_time=timezone.now() - timedelta(days=95)
        )

        purge_old_login_history_task()
        self.assertFalse(UserLoginHistory.objects.filter(pk=old_login.pk).exists())

        # Create old completed deletion job (>30 days old)
        old_job = DeletionJob.objects.create(
            user_id=self.user.id,
            user_email="deleted@example.com",
            status="done",
        )
        DeletionJob.objects.filter(pk=old_job.pk).update(
            finished_at=timezone.now() - timedelta(days=35)
        )

        purge_completed_gdpr_jobs_task()
        self.assertFalse(DeletionJob.objects.filter(pk=old_job.pk).exists())

    # =========================================================================
    # V1-API-01, V1-API-02, V1-API-10: Dedicated Invite Gate & DSA Reporting
    # =========================================================================

    def test_get_v1_invites_allocates_five_codes(self):
        """GET /v1/invites ensures an authenticated user receives 5 distinct invite codes."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get("/v1/invites")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get("success"))
        self.assertEqual(resp.data.get("count"), 5)
        self.assertEqual(len(resp.data.get("data")), 5)

        first_codes = [item["code"] for item in resp.data["data"]]
        self.assertEqual(len(set(first_codes)), 5)

        # Idempotent second fetch returns the same 5 codes without duplicating
        resp2 = self.client.get("/v1/invites")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data.get("count"), 5)
        second_codes = [item["code"] for item in resp2.data["data"]]
        self.assertEqual(first_codes, second_codes)

    def test_redeem_v1_invites_flow_and_validation(self):
        """POST /v1/invites/redeem validates and atomically claims single-use codes."""
        other_user = User.objects.create_user(
            email="other_sharer@example.com",
            name="Other Sharer",
            password="StrongPassword123!",
        )
        invite = Invite.objects.create(code="EXCLUSIVE_2026", kind="standard", owner_user=other_user)

        # 1. Invalid/Nonexistent code
        self.client.force_authenticate(user=self.user)
        bad_resp = self.client.post("/v1/invites/redeem", {"code": "NONEXISTENT_CODE"}, format="json")
        self.assertEqual(bad_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_resp.data.get("code"), "INVITE_INVALID")

        # 2. Self-redeem not allowed
        self.client.force_authenticate(user=other_user)
        self_resp = self.client.post("/v1/invites/redeem", {"code": "EXCLUSIVE_2026"}, format="json")
        self.assertEqual(self_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self_resp.data.get("code"), "INVITE_SELF_REDEEM_NOT_ALLOWED")

        # 3. Successful redemption by valid user
        self.client.force_authenticate(user=self.user)
        good_resp = self.client.post("/v1/invites/redeem", {"code": "EXCLUSIVE_2026"}, format="json")
        self.assertEqual(good_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(good_resp.data.get("success"))

        invite.refresh_from_db()
        self.assertEqual(invite.used_by, self.user)
        self.assertIsNotNone(invite.used_at)

        # 4. User cannot claim another invite code
        third_user = User.objects.create_user(
            email="third@example.com",
            name="Third",
            password="StrongPassword123!",
        )
        Invite.objects.create(code="SECOND_CODE", kind="standard", owner_user=third_user)
        already_claimed_resp = self.client.post("/v1/invites/redeem", {"code": "SECOND_CODE"}, format="json")
        self.assertEqual(already_claimed_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(already_claimed_resp.data.get("code"), "INVITE_ALREADY_CLAIMED")

        # 5. Already used code fails with INVITE_ALREADY_USED for new user
        fresh_user = User.objects.create_user(
            email="fresh@example.com",
            name="Fresh",
            password="StrongPassword123!",
        )
        self.client.force_authenticate(user=fresh_user)
        reused_resp = self.client.post("/v1/invites/redeem", {"code": "EXCLUSIVE_2026"}, format="json")
        self.assertEqual(reused_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(reused_resp.data.get("code"), "INVITE_ALREADY_USED")

        # 6. Bypass code succeeds
        bypass_resp = self.client.post("/v1/invites/redeem", {"code": "APPLE_REVIEW"}, format="json")
        self.assertEqual(bypass_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(bypass_resp.data.get("success"))

    def test_post_v1_reports_dsa_notice_intake(self):
        """POST /v1/reports receives DSA Article 16 notice and action submissions."""
        self.client.force_authenticate(user=self.user)
        report_payload = {
            "target_type": "user",
            "target_id": str(self.user.id),
            "reason": "harassment",
            "details": "DSA Article 16 notice test report submission.",
        }
        resp = self.client.post("/v1/reports", report_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data.get("success"))

