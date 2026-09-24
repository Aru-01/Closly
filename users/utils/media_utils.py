import io
import os
import logging
from urllib.parse import urlparse
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

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


def compress_chat_image(image_file, max_size=(1280, 1280), quality=75):
    """
    Compresses and optimizes chat attachment images to reduce storage and bandwidth.
    - Preserves correct EXIF orientation (e.g. smartphone camera orientation).
    - Proportional downscaling if dimensions exceed max_size (default 1280x1280).
    - Converts transparent PNG/WebP to clean RGB with white background for JPEG.
    - Compresses to standard JPEG at quality=75 with optimization enabled.
    Returns an InMemoryUploadedFile, or gracefully falls back to the original file if uncompressed.
    """
    if not image_file:
        return image_file

    try:
        image_file.seek(0)
        img = Image.open(image_file)

        # Transpose according to EXIF orientation tag if present
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Resize image proportionally to fit within max dimensions
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Convert palette or transparent formats to RGB
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            mask = img.split()[-1] if len(img.split()) == 4 else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Compress to in-memory JPEG
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        buffer.seek(0)

        # Format filename
        orig_name = getattr(image_file, 'name', 'chat_img.jpg')
        base_name, _ = os.path.splitext(orig_name)
        new_filename = f"{base_name[:40]}.jpg"

        compressed_file = InMemoryUploadedFile(
            file=buffer,
            field_name=getattr(image_file, 'field_name', 'image'),
            name=new_filename,
            content_type='image/jpeg',
            size=buffer.getbuffer().nbytes,
            charset=None
        )
        return compressed_file
    except Exception as e:
        logger.warning(f"Chat image compression skipped due to error: {e}")
        try:
            image_file.seek(0)
        except Exception:
            pass
        return image_file

