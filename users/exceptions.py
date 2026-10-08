"""
Custom domain exceptions for users app.
(Dead exception handler removed per P-17 / P-23; global handler lives in Config.exceptions)
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class CustomAPIException(APIException):
    """
    Base class for custom API exceptions.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An error occurred"
    default_code = "error"

    def __init__(self, detail=None, errors=None, status_code=None):
        self.detail = detail or self.default_detail
        self.errors = errors or {}
        if status_code:
            self.status_code = status_code


class EmailNotVerifiedException(CustomAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Email address is not verified. Please verify your email to continue."


class InvalidTokenException(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid or expired token"


class UserNotFoundException(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "User not found"


class AccountInactiveException(CustomAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "User account is inactive"


class InvalidCredentialsException(CustomAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Invalid email or password"


class EmailAlreadyExistsException(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An account with this email already exists"


class PasswordMismatchException(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Passwords do not match"


class WeakPasswordException(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Password does not meet security requirements"


class AgeRestrictionException(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "You must be at least 16 years of age to register"