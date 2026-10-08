import uuid
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.http import Http404
from django.db import IntegrityError, DatabaseError
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Global exception handler for Closly REST API (P-17).
    Guarantees that ALL responses — including unhandled Python exceptions,
    database outages, and missing object lookups — return consistent JSON
    instead of raw HTML 500 error pages.
    Never leaks SQL query details, table constraints, or internal tracebacks.
    """
    # 1. First, check if DRF's built-in handler recognizes this exception
    response = exception_handler(exc, context)

    if response is not None:
        errors_data = response.data
        message = "Request could not be processed."

        # Extract human-friendly error message
        if isinstance(errors_data, dict):
            if 'detail' in errors_data:
                message = str(errors_data['detail'])
            elif errors_data:
                first_key = next(iter(errors_data))
                first_val = errors_data[first_key]
                if isinstance(first_val, list) and first_val:
                    message = f"{first_key}: {first_val[0]}"
                else:
                    message = f"{first_key}: {first_val}"
        elif isinstance(errors_data, list) and errors_data:
            message = str(errors_data[0])

        status_code_map = {
            status.HTTP_400_BAD_REQUEST: "VALIDATION_ERROR",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
            status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_ERROR",
        }
        err_code = status_code_map.get(response.status_code, "ERROR")

        response.data = {
            "success": False,
            "code": err_code,
            "message": message,
            "errors": errors_data if isinstance(errors_data, dict) else {"detail": errors_data}
        }
        return response

    # 2. Handle uncaught exceptions that DRF standard handler returns None for:
    error_id = str(uuid.uuid4())
    view_name = context.get('view').__class__.__name__ if context.get('view') else 'UnknownView'
    logger.error(f"Intercepted unhandled exception [{error_id}] in {view_name}: {exc}", exc_info=True)

    # A. Resource Not Found (e.g. Model.DoesNotExist, Http404)
    if isinstance(exc, (ObjectDoesNotExist, Http404)):
        return Response({
            "success": False,
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "errors": {"detail": "Resource not found."}
        }, status=status.HTTP_404_NOT_FOUND)

    # B. Token & Authentication Errors (TokenError, InvalidToken)
    if isinstance(exc, (TokenError, InvalidToken)):
        return Response({
            "success": False,
            "code": "TOKEN_INVALID",
            "message": "Authentication token is invalid or expired. Please log in again.",
            "errors": {"detail": "Token invalid or expired."}
        }, status=status.HTTP_401_UNAUTHORIZED)

    # C. Database Outage & Integrity Errors (P-17: Never leak SQL constraint names or raw SQL)
    if isinstance(exc, DatabaseError):
        if isinstance(exc, IntegrityError):
            return Response({
                "success": False,
                "code": "RESOURCE_CONFLICT",
                "message": "A record with this information already exists.",
                "errors": {"detail": "Unique constraint or resource conflict."}
            }, status=status.HTTP_409_CONFLICT)

        # Database connection outage or server-side DB failure -> 503 Service Unavailable
        return Response({
            "success": False,
            "code": "DATABASE_UNAVAILABLE",
            "message": "Database service is temporarily unavailable. Please retry in a few moments.",
            "error_id": error_id,
            "errors": {"detail": "Database unavailable."}
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={'Retry-After': '5'})

    # D. Django Validation Errors
    if isinstance(exc, DjangoValidationError):
        return Response({
            "success": False,
            "code": "VALIDATION_ERROR",
            "message": "Validation error.",
            "errors": exc.message_dict if hasattr(exc, 'message_dict') else {"detail": exc.messages}
        }, status=status.HTTP_400_BAD_REQUEST)

    # E. Absolute Fallback for unexpected 500: Return Clean Sanitized JSON (Never leak str(exc) or internal paths)
    return Response({
        "success": False,
        "code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected server error occurred. Please try again.",
        "error_id": error_id,
        "errors": {"detail": f"An internal error occurred. Error ID: {error_id}"}
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
