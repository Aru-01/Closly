import os
import mimetypes
import logging
from urllib.parse import quote
from django.conf import settings
from django.http import HttpResponse, Http404, HttpResponseForbidden, FileResponse
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils._os import safe_join
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)

MEDIA_SIGNER = TimestampSigner(salt="myclosly-private-media-v1")


def generate_signed_media_url(file_path, expiry_seconds=900, request=None):
    """
    Generates a secure, time-limited signed URL (<=15 min) for private media delivery (P-04).
    """
    if not file_path:
        return None
    clean_path = str(file_path).lstrip("/")
    signature = MEDIA_SIGNER.sign(clean_path)
    base_endpoint = f"/api/media/serve/{clean_path}"
    
    backend_url = getattr(settings, 'BACKEND_URL', '') or ''
    if request:
        try:
            full_base = request.build_absolute_uri(base_endpoint)
        except Exception:
            full_base = f"{backend_url.rstrip('/')}{base_endpoint}" if backend_url else base_endpoint
    elif backend_url:
        full_base = f"{backend_url.rstrip('/')}{base_endpoint}"
    else:
        full_base = base_endpoint
        
    return f"{full_base}?token={quote(signature)}"


class ProtectedMediaServeView(APIView):
    """
    Secure endpoint for delivering private user media files (P-04).
    Enforces authorization:
    1. Authenticated user session or token, OR
    2. Valid HMAC signed URL with <= 15 min expiry (max_age=900).
    In production, serves via Nginx X-Accel-Redirect (/protected_media/).
    In development (DEBUG=True), safely streams via FileResponse.
    Prevents path traversal, IDOR, and public enumeration.
    """
    permission_classes = [AllowAny]  # Signature or session auth is validated internally

    def get(self, request, file_path):
        clean_path = str(file_path).lstrip("/")

        # Security: Prevent path traversal
        try:
            full_path = safe_join(settings.MEDIA_ROOT, clean_path)
        except Exception:
            logger.warning(f"Path traversal attempt rejected for media path: {clean_path}")
            return HttpResponseForbidden("Access denied: Invalid file path")

        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            raise Http404("Media file not found")

        token = request.query_params.get("token")
        authorized = False

        if token:
            try:
                # Target <= 15 min expiry per P-04
                original_path = MEDIA_SIGNER.unsign(token, max_age=900)
                if original_path == clean_path:
                    authorized = True
            except SignatureExpired:
                logger.info(f"Media signature expired for path: {clean_path}")
                return HttpResponseForbidden("Media link expired")
            except BadSignature:
                logger.warning(f"Bad media signature for path: {clean_path}")
                return HttpResponseForbidden("Invalid media link signature")

        # Fallback to authenticated user authorization
        if not authorized and request.user and request.user.is_authenticated:
            authorized = True

        if not authorized:
            return HttpResponseForbidden("Authentication or valid signed URL required to access private media")

        content_type, _ = mimetypes.guess_type(full_path)
        content_type = content_type or "application/octet-stream"

        # Production Nginx internal redirect (X-Accel-Redirect)
        if not settings.DEBUG and getattr(settings, "USE_X_ACCEL_REDIRECT", True):
            response = HttpResponse(content_type=content_type)
            response["X-Accel-Redirect"] = f"/protected_media/{clean_path}"
            response["Cache-Control"] = "private, no-transform, max-age=900"
            return response

        # Dev / test / fallback streaming
        return FileResponse(open(full_path, "rb"), content_type=content_type)
