from urllib.parse import urlparse
from django.conf import settings

LOCAL_DEV_HOSTS = {'127.0.0.1', 'localhost', '0.0.0.0', '10.0.2.2', 'testserver'}


def _normalize_media_url(url_str):
    if not url_str:
        return url_str
    try:
        parsed = urlparse(url_str)
        hostname = (parsed.hostname or '').lower()
        # If running locally (127.0.0.1, localhost, etc.), never force HTTPS because local dev server is plain HTTP
        if hostname in LOCAL_DEV_HOSTS:
            if url_str.startswith('https://'):
                return 'http://' + url_str[8:]
            return url_str
        # For non-local hosts, honor FORCE_HTTPS_MEDIA_URL
        if getattr(settings, 'FORCE_HTTPS_MEDIA_URL', False) and url_str.startswith('http://'):
            return 'https://' + url_str[7:]
    except Exception:
        pass
    return url_str


def build_absolute_media_url(file_or_url, request=None):
    """
    Constructs a fully qualified absolute URL with scheme and host for media files.
    Ensures URLs start with 'https://' when configured or when accessed via secure proxies,
    while keeping local development hosts (127.0.0.1, localhost, etc.) on 'http://' to
    prevent SSL handshake failures.
    """
    if not file_or_url:
        return None

    if hasattr(file_or_url, 'url'):
        try:
            raw_url = file_or_url.url
        except Exception:
            return None
    else:
        raw_url = str(file_or_url)

    if not raw_url:
        return None

    # If it's already a full URL
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return _normalize_media_url(raw_url)

    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    if not raw_url.startswith(media_url):
        clean_path = f"{media_url.rstrip('/')}/{raw_url.lstrip('/')}"
    else:
        clean_path = raw_url if raw_url.startswith('/') else f"/{raw_url}"

    # Try building with request first if available
    if request is not None:
        try:
            abs_url = request.build_absolute_uri(clean_path)
            return _normalize_media_url(abs_url)
        except Exception:
            pass

    # Fallback to BACKEND_URL setting
    backend_url = getattr(settings, 'BACKEND_URL', '') or ''
    if backend_url:
        base = backend_url.rstrip('/')
        full_url = f"{base}{clean_path}"
        return _normalize_media_url(full_url)

    return clean_path
