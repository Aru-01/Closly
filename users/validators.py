"""
Custom validators for user input validation
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import re
from datetime import date


def validate_password_strength(password):
    """
    Validate password strength
    
    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    
    Args:
        password (str): Password to validate
        
    Raises:
        ValidationError: If password doesn't meet requirements
    """
    if len(password) < 8:
        raise ValidationError(
            _('Password must be at least 8 characters long.'),
            code='password_too_short'
        )
    
    if not re.search(r'[A-Z]', password):
        raise ValidationError(
            _('Password must contain at least one uppercase letter.'),
            code='password_no_upper'
        )
    
    if not re.search(r'[a-z]', password):
        raise ValidationError(
            _('Password must contain at least one lowercase letter.'),
            code='password_no_lower'
        )
    
    if not re.search(r'\d', password):
        raise ValidationError(
            _('Password must contain at least one number.'),
            code='password_no_number'
        )
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValidationError(
            _('Password must contain at least one special character.'),
            code='password_no_special'
        )


def validate_email_format(email):
    """
    Validate email format (additional validation beyond Django's EmailField)
    
    Args:
        email (str): Email to validate
        
    Raises:
        ValidationError: If email format is invalid
    """
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        raise ValidationError(
            _('Enter a valid email address.'),
            code='invalid_email'
        )
    
    # Check for common typos in popular email domains
    common_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
    domain = email.split('@')[1].lower()
    
    # List of common typos
    typo_domains = {
        'gmial.com': 'gmail.com',
        'gmai.com': 'gmail.com',
        'yahooo.com': 'yahoo.com',
        'hotmial.com': 'hotmail.com',
    }
    
    if domain in typo_domains:
        raise ValidationError(
            _(f'Did you mean {typo_domains[domain]}?'),
            code='possible_typo'
        )


def validate_name(name):
    """
    Validate user's name
    
    Args:
        name (str): Name to validate
        
    Raises:
        ValidationError: If name is invalid
    """
    if not name or len(name.strip()) == 0:
        raise ValidationError(
            _('Name cannot be empty.'),
            code='name_empty'
        )
    
    if len(name) < 2:
        raise ValidationError(
            _('Name must be at least 2 characters long.'),
            code='name_too_short'
        )
    
    if len(name) > 150:
        raise ValidationError(
            _('Name cannot exceed 150 characters.'),
            code='name_too_long'
        )
    
    # Check if name contains only letters, spaces, hyphens, and apostrophes
    if not re.match(r"^[a-zA-Z\s\-']+$", name):
        raise ValidationError(
            _('Name can only contain letters, spaces, hyphens, and apostrophes.'),
            code='name_invalid_characters'
        )


def validate_date_of_birth(dob):
    """
    Validate date of birth
    
    Args:
        dob (date): Date of birth to validate
        
    Raises:
        ValidationError: If date of birth is invalid
    """
    if not dob:
        return  # DOB might be optional
    
    today = date.today()
    
    # Check if date is in the future
    if dob > today:
        raise ValidationError(
            _('Date of birth cannot be in the future.'),
            code='dob_future'
        )
    
    # Calculate age
    age = today.year - dob.year
    if today.month < dob.month or (today.month == dob.month and today.day < dob.day):
        age -= 1
    
    # Check minimum age (13 years for most platforms)
    if age < 13:
        raise ValidationError(
            _('You must be at least 13 years old to register.'),
            code='dob_too_young'
        )
    
    # Check maximum age (120 years - to catch obvious errors)
    if age > 120:
        raise ValidationError(
            _('Please enter a valid date of birth.'),
            code='dob_too_old'
        )


def validate_image_file(image, max_mb=30):
    """
    Validate uploaded image file size and format.
    Default maximum size is 30MB.
    """
    if not image:
        return image

    max_size = max_mb * 1024 * 1024
    if image.size > max_size:
        raise ValidationError(
            _(f'Image file size exceeds the {max_mb}MB limit. Please upload a smaller image.'),
            code='image_too_large'
        )

    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif']
    file_name = getattr(image, 'name', '')
    if '.' in file_name:
        ext = '.' + file_name.lower().split('.')[-1]
        if ext not in valid_extensions:
            raise ValidationError(
                _('Only JPG, JPEG, PNG, GIF, WebP, and HEIC images are allowed.'),
                code='invalid_image_format'
            )

    # Sanitize and shorten filename if it is too long (prevents OS and storage length issues)
    if hasattr(image, 'name') and image.name and len(image.name) > 80:
        import os
        base, ext = os.path.splitext(image.name)
        image.name = f"{base[:40]}_{abs(hash(base)) % 1000000}{ext}"

    return image


def validate_profile_picture(image):
    """
    Validate profile picture upload (max 30MB)
    """
    return validate_image_file(image, max_mb=30)


def validate_password_match(password, confirm_password):
    """
    Validate that password and confirm_password match
    
    Args:
        password (str): Password
        confirm_password (str): Confirmation password
        
    Raises:
        ValidationError: If passwords don't match
    """
    if password != confirm_password:
        raise ValidationError(
            _('Passwords do not match.'),
            code='password_mismatch'
        )