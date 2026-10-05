import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _dispatch_email(subject, plain_message, recipient_list, html_message=None):
    """
    Helper to dispatch email asynchronously via Celery task, falling back
    to synchronous send_mail if Celery/broker is unavailable.
    """
    try:
        from users.tasks import send_email_async_task
        send_email_async_task.delay(
            subject=subject,
            message=plain_message,
            recipient_list=recipient_list,
            html_message=html_message
        )
        return True
    except Exception as exc:
        logger.warning(f"Celery enqueue failed ({exc}), falling back to direct send_mail.")
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                recipient_list=recipient_list,
                html_message=html_message,
                fail_silently=False,
            )
            return True
        except Exception as e:
            logger.error(f"Synchronous fallback email delivery failed to {recipient_list}: {e}")
            return False


def send_otp_email(user, otp):
    """
    Send 6-digit OTP to user's email asynchronously.
    """
    try:
        subject = 'Your Closly Verification Code'
        html_message = render_to_string('emails/otp_email.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        return _dispatch_email(subject, plain_message, [user.email], html_message=html_message)
    except Exception as e:
        logger.error(f"Error rendering OTP email for {user.email}: {e}")
        return False


def send_password_reset_email(user, otp):
    """
    Send password reset OTP to user asynchronously.
    """
    try:
        subject = 'Reset Your Password - Closly'
        html_message = render_to_string('emails/reset_password.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Closly',
            'expiry_minutes': 10,
        })
        plain_message = strip_tags(html_message)
        return _dispatch_email(subject, plain_message, [user.email], html_message=html_message)
    except Exception as e:
        logger.error(f"Error rendering password reset email for {user.email}: {e}")
        return False


def send_welcome_email(user):
    """
    Send welcome email to newly registered user asynchronously.
    """
    try:
        subject = 'Welcome to Closly!'
        html_message = render_to_string('emails/welcome.html', {
            'user': user,
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        return _dispatch_email(subject, plain_message, [user.email], html_message=html_message)
    except Exception as e:
        logger.error(f"Error rendering welcome email for {user.email}: {e}")
        return False


def send_account_deletion_email(user, summary=None):
    """
    Send confirmation email when account is deleted asynchronously.
    """
    try:
        subject = 'Your Closly Account Has Been Deleted'
        html_message = render_to_string('emails/account_deleted.html', {
            'user': user,
            'summary': summary or {},
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        return _dispatch_email(subject, plain_message, [user.email], html_message=html_message)
    except Exception as e:
        logger.error(f"Error rendering account deletion email for {user.email}: {e}")
        return False
