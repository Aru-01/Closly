"""
Utility functions for user authentication and token management
"""

import secrets
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth


# Initialize Firebase Admin SDK
def initialize_firebase():
    """
    Initialize Firebase Admin SDK with service account credentials
    This should be called once when Django starts
    """
    if not firebase_admin._apps:
        firebase_credentials_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
        if not firebase_credentials_path:
            print("Warning: FIREBASE_CREDENTIALS_PATH is not set in settings. Firebase Admin SDK will not be initialized.")
            return

        cred = credentials.Certificate(firebase_credentials_path)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully")


def generate_otp(length=4):
    """
    Generate a random OTP of a given length
    """
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])

def send_otp_email(user, otp):
    """
    Send OTP to user's email
    """
    try:
        subject = 'Your One-Time Password (OTP)'
        html_message = render_to_string('emails/otp_email.html', {
            'user': user,
            'otp': otp,
            'site_name': 'Your App Name',
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
        print(f"Error sending OTP email: {str(e)}")
        return False


def verify_firebase_token(id_token):
    """
    Verify Firebase ID token and return decoded token data
    
    Args:
        id_token (str): Firebase ID token from client
        
    Returns:
        dict: Decoded token data with user info
        
    Raises:
        Exception: If token is invalid or expired
    """
    try:
        # Verify the ID token and decode it
        decoded_token = firebase_auth.verify_id_token(id_token, clock_skew_seconds=5)
        return decoded_token
    except Exception as e:
        raise Exception(f"Invalid Firebase token: {str(e)}")


def get_client_ip(request):
    """
    Get client IP address from request
    
    Args:
        request: Django request object
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """
    Get user agent string from request
    
    Args:
        request: Django request object
        
    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def send_verification_email(user, verification_url):
    """
    Send email verification link to user
    
    Args:
        user: User instance
        verification_url (str): Full URL for email verification
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Verify Your Email Address'
        
        # Render HTML email template
        html_message = render_to_string('emails/verify_email.html', {
            'user': user,
            'verification_url': verification_url,
            'site_name': 'Your App Name',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
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
        print(f"Error sending verification email: {str(e)}")
        return False


def send_password_reset_email(user, reset_url):
    """
    Send password reset link to user
    
    Args:
        user: User instance
        reset_url (str): Full URL for password reset
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Reset Your Password'
        
        # Render HTML email template
        html_message = render_to_string('emails/reset_password.html', {
            'user': user,
            'reset_url': reset_url,
            'site_name': 'Your App Name',
            'expiry_hours': settings.PASSWORD_RESET_TOKEN_EXPIRY_HOURS,
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
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
        print(f"Error sending password reset email: {str(e)}")
        return False


def send_welcome_email(user):
    """
    Send welcome email to newly registered user
    
    Args:
        user: User instance
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Welcome to Our App!'
        
        # Render HTML email template
        html_message = render_to_string('emails/welcome.html', {
            'user': user,
            'site_name': 'Your App Name',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
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
        print(f"Error sending welcome email: {str(e)}")
        return False


def send_account_deletion_email(user):
    """
    Send confirmation email when account is deleted
    
    Args:
        user: User instance
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Your Account Has Been Deleted'
        
        # Render HTML email template
        html_message = render_to_string('emails/account_deleted.html', {
            'user': user,
            'site_name': 'Your App Name',
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
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
        print(f"Error sending account deletion email: {str(e)}")
        return False


def calculate_age(date_of_birth):
    """
    Calculate age from date of birth
    
    Args:
        date_of_birth (date): Date of birth
        
    Returns:
        int: Age in years
    """
    from datetime import date
    
    if not date_of_birth:
        return None
    
    today = date.today()
    age = today.year - date_of_birth.year
    
    # Adjust if birthday hasn't occurred this year
    if today.month < date_of_birth.month or \
       (today.month == date_of_birth.month and today.day < date_of_birth.day):
        age -= 1
    
    return age


def validate_age(date_of_birth, min_age=13):
    """
    Validate if user meets minimum age requirement
    
    Args:
        date_of_birth (date): Date of birth
        min_age (int): Minimum age required (default 13)
        
    Returns:
        bool: True if user meets age requirement, False otherwise
    """
    age = calculate_age(date_of_birth)
    
    if age is None:
        return False
    
    return age >= min_age