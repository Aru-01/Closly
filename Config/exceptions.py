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
    Global exception handler for Closly REST API.
    Guarantees that ALL responses — including unhandled Python exceptions,
    database errors, and missing object lookups — return consistent JSON
    instead of raw HTML 500 error pages.
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

        response.data = {
            "success": False,
            "message": message,
            "errors": errors_data if isinstance(errors_data, dict) else {"detail": errors_data}
        }
        return response

    # 2. Handle uncaught exceptions that DRF standard handler returns None for:
    view_name = context.get('view').__class__.__name__ if context.get('view') else 'UnknownView'
    logger.error(f"Intercepted unhandled exception in {view_name}: {exc}", exc_info=True)

    # A. Resource Not Found (e.g. Model.DoesNotExist, Http404)
    if isinstance(exc, (ObjectDoesNotExist, Http404)):
        return Response({
            "success": False,
            "message": "The requested resource was not found.",
            "errors": {"detail": str(exc)}
        }, status=status.HTTP_404_NOT_FOUND)

    # B. Token & Authentication Errors (TokenError, InvalidToken)
    if isinstance(exc, (TokenError, InvalidToken)):
        return Response({
            "success": False,
            "message": "Authentication token is invalid or expired. Please log in again.",
            "errors": {"detail": str(exc)}
        }, status=status.HTTP_401_UNAUTHORIZED)

    # C. Database Constraint / Integrity Errors
    if isinstance(exc, (IntegrityError, DatabaseError)):
        err_str = str(exc)
        friendly_msg = "A record with this information already exists." if "unique constraint" in err_str.lower() else "Database constraint violation."
        return Response({
            "success": False,
            "message": friendly_msg,
            "errors": {"detail": err_str}
        }, status=status.HTTP_400_BAD_REQUEST)

    # D. Django Validation Errors
    if isinstance(exc, DjangoValidationError):
        return Response({
            "success": False,
            "message": "Validation error.",
            "errors": {"detail": exc.message_dict if hasattr(exc, 'message_dict') else exc.messages}
        }, status=status.HTTP_400_BAD_REQUEST)

    # E. Invalid Parameter / Value / Type / Key Errors
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return Response({
            "success": False,
            "message": f"Invalid parameter or data format: {str(exc)}",
            "errors": {"detail": str(exc)}
        }, status=status.HTTP_400_BAD_REQUEST)

    # F. Absolute Fallback for unexpected 500: Return Clean JSON (Never HTML!)
    return Response({
        "success": False,
        "message": "An unexpected server error occurred. Please try again.",
        "errors": {"detail": str(exc)}
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
