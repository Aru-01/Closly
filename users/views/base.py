import logging
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)

def standard_response(success=True, message="", data=None, errors=None, status_code=status.HTTP_200_OK, code=None):
    """
    Create standardized API response with stable machine-readable code.
    """
    response_data = {
        'success': success,
        'message': message,
    }

    if code is not None:
        response_data['code'] = code
    elif not success:
        status_code_map = {
            status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
            status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_ERROR",
        }
        response_data['code'] = status_code_map.get(status_code, "ERROR")

    if data is not None:
        response_data['data'] = data

    if errors is not None:
        response_data['errors'] = errors

    return Response(response_data, status=status_code)


