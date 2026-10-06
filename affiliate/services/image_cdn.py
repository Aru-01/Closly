"""
affiliate/services/image_cdn.py
Image asset replication service for Audit CF-18.
Handles:
- SSRF-safe URL validation (blocking private/loopback/link-local/metadata IPs)
- Secure streaming download with byte-size caps and timeouts
- SHA-256 content hashing for integrity and deduplication
- Django default_storage integration (S3 / Cloudflare R2 / Bunny / FileSystem)
- CDN URL generation
- Ended brand image purge for AWIN compliance
"""
import ipaddress
import logging
import mimetypes
import socket
import urllib.parse
import hashlib
from typing import Optional, Tuple
import requests

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

logger = logging.getLogger(__name__)

# Disallowed internal/private hostnames
BLOCKED_HOSTNAMES = {
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    '169.254.169.254',  # AWS/GCP/Azure link-local metadata
    'metadata.google.internal',
    'instance-data',
}


class SSRFValidationError(ValueError):
    """Raised when an external URL targets a private/internal network address."""
    pass


def validate_image_url_safe(url: str) -> bool:
    """
    Validate that an external asset URL is safe to fetch:
    1. Scheme must be HTTP or HTTPS.
    2. Hostname must not be localhost or metadata service.
    3. Resolved IP must NOT be in private, loopback, link-local, or reserved ranges.
    """
    if not url or not isinstance(url, str):
        return False

    url_clean = url.strip()
    parsed = urllib.parse.urlsplit(url_clean)

    if parsed.scheme.lower() not in ('http', 'https'):
        logger.warning(f"SSRF Guard: Rejected non-http scheme in URL: {url_clean[:100]}")
        return False

    hostname = (parsed.hostname or '').strip().lower()
    if not hostname or hostname in BLOCKED_HOSTNAMES:
        logger.warning(f"SSRF Guard: Blocked internal hostname '{hostname}'")
        return False

    if hostname.endswith(('.internal', '.local', '.onion')):
        logger.warning(f"SSRF Guard: Blocked internal TLD hostname '{hostname}'")
        return False

    # Resolve hostname to IPs and check for private networks
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private or
                ip_obj.is_loopback or
                ip_obj.is_link_local or
                ip_obj.is_reserved or
                ip_obj.is_multicast
            ):
                logger.warning(f"SSRF Guard: Hostname '{hostname}' resolved to private/reserved IP {ip_str}")
                return False
    except (socket.gaierror, ValueError) as err:
        logger.warning(f"SSRF Guard: DNS resolution failed for '{hostname}': {err}")
        return False

    return True


def fetch_and_replicate_image(
    product,
    max_bytes: Optional[int] = None,
    timeout: Optional[int] = None,
) -> Optional[str]:
    """
    Safely download remote merchant image, compute SHA-256 hash, store into storage,
    and update product.cdn_image_url.
    Returns the public CDN/media URL on success, or None on failure.
    """
    source_url = (product.image_url or '').strip()
    if not source_url:
        return None

    if not validate_image_url_safe(source_url):
        logger.warning(f"SSRF Guard blocked download for product {product.id}: {source_url}")
        return None

    max_size = max_bytes or getattr(settings, 'MYC_IMAGE_MAX_SIZE_BYTES', 10 * 1024 * 1024)
    req_timeout = timeout or getattr(settings, 'MYC_IMAGE_DOWNLOAD_TIMEOUT', 10)

    try:
        with requests.get(
            source_url,
            stream=True,
            timeout=req_timeout,
            allow_redirects=True,
            headers={'User-Agent': getattr(settings, 'MYC_BOT_USER_AGENT', 'mycloslybot/1.0 (+https://myclosly.com/bot)')},
        ) as resp:
            if resp.status_code != 200:
                logger.warning(f"Image fetch returned HTTP {resp.status_code} for {source_url[:100]}")
                return None

            # Validate final redirect destination against SSRF
            final_url = resp.url
            if final_url != source_url and not validate_image_url_safe(final_url):
                logger.warning(f"SSRF Guard blocked redirect URL: {final_url[:100]}")
                return None

            content_type = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if not content_type.startswith('image/'):
                logger.warning(f"Invalid Content-Type '{content_type}' for {source_url[:100]}")
                return None

            # Stream content in chunks with size limit
            content_chunks = []
            total_bytes = 0
            hasher = hashlib.sha256()

            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    total_bytes += len(chunk)
                    if total_bytes > max_size:
                        logger.warning(f"Image exceeded max size limit of {max_size} bytes: {source_url[:100]}")
                        return None
                    content_chunks.append(chunk)
                    hasher.update(chunk)

            full_content = b"".join(content_chunks)
            image_hash = hasher.hexdigest()

    except Exception as e:
        logger.warning(f"Failed to fetch image for product {product.id} from {source_url[:100]}: {e}")
        return None

    # Determine extension
    ext = mimetypes.guess_extension(content_type) or '.jpg'
    if ext == '.jpe':
        ext = '.jpg'

    # Build storage relative path
    storage_path = f"products/{image_hash[:2]}/{image_hash}{ext}"

    try:
        # Check if already in storage to avoid duplicate writes
        if not default_storage.exists(storage_path):
            default_storage.save(storage_path, ContentFile(full_content))

        # Generate CDN / media URL
        cdn_base = getattr(settings, 'MYC_CDN_BASE_URL', None)
        s3_custom_domain = getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', None)

        if cdn_base:
            cdn_url = f"{cdn_base.rstrip('/')}/media/{storage_path}"
        elif s3_custom_domain:
            cdn_url = f"https://{s3_custom_domain}/media/{storage_path}"
        else:
            cdn_url = default_storage.url(storage_path)

        # Update product record
        product.cdn_image_url = cdn_url
        product.image_hash = image_hash
        product.image_replicated_at = timezone.now()
        product.save(update_fields=['cdn_image_url', 'image_hash', 'image_replicated_at'])

        logger.info(f"Replicated image for product {product.id} -> {cdn_url}")
        return cdn_url

    except Exception as e:
        logger.error(f"Error saving replicated image to storage for product {product.id}: {e}", exc_info=True)
        return None


def purge_ended_brand_images(brand) -> int:
    """
    AWIN compliance rule (Ch4 §1.2: never serve images of an ended programme).
    When Brand.status becomes 'ended', purge image URLs and deactivate products.
    Returns count of updated products.
    """
    from affiliate.models import AffiliateProduct
    updated = AffiliateProduct.objects.filter(brand_ref=brand).update(
        cdn_image_url='',
        image_url='',
        is_active=False,
    )
    logger.info(f"Purged images and deactivated {updated} products for ended brand '{brand.name}'.")
    return updated
