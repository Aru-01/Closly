"""
Automated tests for AWS SES SMTP email settings, runtime development isolation,
and network configuration safety.
Credentials and secrets are strictly verified for presence without logging or hardcoding.
"""

import socket
from django.test import TestCase, override_settings
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
