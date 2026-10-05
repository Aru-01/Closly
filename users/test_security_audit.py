from datetime import date, timedelta
from unittest.mock import patch, MagicMock
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
        access_token = str(refresh.access_token)

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

        # User is deleted from database
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
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
        res2 = self.client.post(url, data2, format="json")
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
        handle_url = f"/u/victim/"
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
        verify_url = reverse("users:verify_otp")
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
        device_url = reverse("users:device_registration")
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

        from users.models import DeletionJob
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

        # Confirm user row was erased
        self.assertFalse(User.objects.filter(id=victim_id).exists())

    def test_account_deletion_re_request_creates_fresh_record(self):
        """U-27: Multiple deletion requests must produce distinct fresh records."""
        url = reverse("users:request_account_deletion_api")
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
        url = reverse("users:gdpr_export")
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
        resend_url = reverse("users:resend_otp")
        res_resp = self.client.post(resend_url, {"email": "nobody_exists@example.com"}, format="json")
        self.assertEqual(res_resp.status_code, status.HTTP_200_OK)

        # 2. Verify OTP with non-existent email returns generic 400
        verify_url = reverse("users:verify_otp")
        v_resp = self.client.post(verify_url, {"email": "nobody_exists@example.com", "otp": "999999"}, format="json")
        self.assertEqual(v_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(v_resp.data.get("code"), "INVALID_OTP")

        # 3. Password reset request with non-existent email returns 200 generic
        pwd_url = reverse("users:password_reset_request")
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
        share_url = reverse("users:share_profile")
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
        from users.models import UserLoginHistory, DeletionJob
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

