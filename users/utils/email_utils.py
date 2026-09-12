import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_otp_email(user, otp):
    """
    Send OTP to user's email.
    """
    try:
        subject = 'Your Closly Verification Code'
        html_message = render_to_string('emails/otp_email.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Error sending OTP email: {str(e)}")
        return False


def send_password_reset_email(user, otp):
    """
    Send password reset OTP to user.
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
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Error sending password reset email: {str(e)}")
        return False


def send_welcome_email(user):
    """
    Send welcome email to newly registered user.
    """
    try:
        subject = 'Welcome to Closly!'
        html_message = render_to_string('emails/welcome.html', {
            'user': user,
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Error sending welcome email: {str(e)}")
        return False


def send_account_deletion_email(user, summary=None):
    """
    Send confirmation email when account is deleted.
    """
    try:
        subject = 'Your Closly Account Has Been Deleted'
        html_message = render_to_string('emails/account_deleted.html', {
            'user': user,
            'summary': summary or {},
            'site_name': 'Closly',
        })
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Error sending account deletion email: {str(e)}")
        return False
