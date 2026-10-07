import io
import os
import uuid
import hashlib
import logging
from PIL import Image, ImageOps
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from closet.exceptions import AIImageValidationError

logger = logging.getLogger(__name__)


def validate_and_sanitize_image(image_file, max_dimension: int = 1024, quality: int = 80) -> tuple[bytes, str, str]:
    """
    Validates and sanitizes an uploaded image completely in-memory:
    1. Validates file presence and reads raw bytes.
    2. Verifies image integrity and magic bytes via Pillow Image.open().verify().
    3. Transposes orientation according to EXIF orientation tag.
    4. Strips ALL EXIF, GPS, camera metadata, and device identifiers (C-01 GDPR/Privacy).
    5. Proportionally downscales image if dimensions exceed max_dimension (C-06 Token/Cost Optimization).
    6. Converts to standard RGB JPEG with optimization.
    7. Computes a deterministic SHA-256 hash of the sanitized bytes for deduplication & points farming protection.

    Returns:
        tuple (sanitized_jpeg_bytes: bytes, photo_sha256: str, mime_type: str)
    """
    if not image_file:
        raise AIImageValidationError("No image file provided.")

    try:
        image_file.seek(0)
        raw_bytes = image_file.read()
        image_file.seek(0)
    except Exception as e:
        raise AIImageValidationError(f"Could not read uploaded image data: {e}")

    if not raw_bytes:
        raise AIImageValidationError("Uploaded image file is empty.")

    # 1. Verify magic bytes and integrity with Pillow
    try:
        verify_img = Image.open(io.BytesIO(raw_bytes))
        verify_img.verify()
    except Exception as e:
        logger.warning(f"Image integrity verification failed: {e}")
        raise AIImageValidationError("Uploaded file is corrupted or not a valid image format.")

    # 2. Re-open image stream for processing (verify() exhausts the image buffer)
    try:
        img = Image.open(io.BytesIO(raw_bytes))

        # Handle EXIF orientation transposition
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # 3. Downscale proportionally to fit within max_dimension
        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        # 4. Convert palette, alpha, or CMYK formats to clean RGB
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            mask = img.split()[-1] if len(img.split()) == 4 else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 5. Compress to in-memory JPEG without metadata (strips all EXIF/GPS tags)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        sanitized_bytes = buffer.getvalue()

        # 6. Compute SHA-256 of the sanitized image
        photo_sha256 = hashlib.sha256(sanitized_bytes).hexdigest()

        return sanitized_bytes, photo_sha256, 'image/jpeg'

    except AIImageValidationError:
        raise
    except Exception as e:
        logger.error(f"Error during image sanitization: {e}", exc_info=True)
        raise AIImageValidationError("Failed to process and sanitize garment image.")


def persist_sanitized_image(sanitized_bytes: bytes, folder: str = "closet_items", prefix: str = "ai_scan_") -> str:
    """
    Safely writes pre-sanitized JPEG bytes to default_storage under a randomized unique path.
    """
    unique_name = f"{prefix}{uuid.uuid4().hex[:16]}.jpg"
    storage_path = f"{folder.strip('/')}/{unique_name}"
    return default_storage.save(storage_path, ContentFile(sanitized_bytes))
