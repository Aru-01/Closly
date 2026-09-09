"""
Custom exception handler for consistent error responses
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import APIException
from django.core.exceptions import ValidationError as DjangoValidationError


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns consistent error format.
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # If the exception is one of our custom exceptions, format the response
    if isinstance(exc, CustomAPIException):
        return Response(
            {
                "success": False,
                "message": exc.detail,
                "errors": exc.errors or {},
            },
            status=exc.status_code,
        )

    # Handle Django validation errors
    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "success": False,
                "message": "Validation error",
                "errors": exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # If DRF handled the exception, format it consistently
    if response is not None:
        custom_response = {
            "success": False,
            "message": "An error occurred",
            "errors": {},
        }

        if isinstance(response.data, dict):
            if "detail" in response.data:
                custom_response["message"] = str(response.data["detail"])
            else:
                custom_response["message"] = "Validation error"
                custom_response["errors"] = response.data
        elif isinstance(response.data, list):
            custom_response["message"] = (
                response.data[0] if response.data else "An error occurred"
            )
        else:
            custom_response["message"] = str(response.data)

        response.data = custom_response

    return response


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
    """Exception raised when user's email is not verified"""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = (
        "Email address is not verified. Please verify your email to continue."
    )


class InvalidTokenException(CustomAPIException):
    """Exception raised when token is invalid or expired"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid or expired token"


class UserNotFoundException(CustomAPIException):
    """Exception raised when user is not found"""

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "User not found"


class AccountInactiveException(CustomAPIException):
    """Exception raised when user account is inactive"""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "User account is inactive"


class InvalidCredentialsException(CustomAPIException):
    """Exception raised when login credentials are invalid"""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Invalid email or password"


class EmailAlreadyExistsException(CustomAPIException):
    """Exception raised when email already exists during registration"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An account with this email already exists"


class PasswordMismatchException(CustomAPIException):
    """Exception raised when passwords don't match"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Passwords do not match"


class WeakPasswordException(CustomAPIException):
    """Exception raised when password doesn't meet requirements"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Password does not meet security requirements"


class AgeRestrictionException(CustomAPIException):
    """Exception raised when user doesn't meet age requirement"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "You must be at least 13 years old to register"