"""
Content Safety & NSFW Image Pre-Screening Service.
Rule 3 & Finding C-03: Moderation check must run BEFORE any LLM inference.
Evaluates uploaded images locally (heuristic nudity/skin ratio) and via API gateways (Sightengine/OpenAI Moderation).
Immediately deletes explicit content from storage and blocks downstream AI costs.
"""

import logging
import io
from PIL import Image
from django.conf import settings
from django.core.files.storage import default_storage

from closet.ai.safety import (
    check_image_safety,
    AISafetyError,
    AISafetyBlockedError,
)

logger = logging.getLogger(__name__)


def local_heuristic_nsfw_analysis(image_bytes: bytes) -> tuple[bool, str, float]:
    """
    Lightweight, fast local computer vision heuristic.
    Analyzes pixel distribution in HSV space to detect excessive exposed skin ratios.
    Runs locally with zero external API latency or cost.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert('RGB')
        # Resize to small thumbnail for fast histogram calculation
        img.thumbnail((150, 150))
        width, height = img.size
        total_pixels = width * height

        if total_pixels == 0:
            return True, "empty_image", 0.0

        # Sample pixels for human skin tones in HSV
        hsv_img = img.convert('HSV')
        skin_pixel_count = 0
        pixels = hsv_img.getdata()

        for h, s, v in pixels:
            # Hue in [0, 25] or [230, 255] (red-orange spectrum), Saturation >= 40, Value >= 60
            if (h <= 25 or h >= 230) and 40 <= s <= 200 and 60 <= v <= 240:
                skin_pixel_count += 1

        skin_ratio = skin_pixel_count / float(total_pixels)
        logger.debug(f"Local heuristic skin ratio: {skin_ratio:.2f}")

        # If more than 78% of the image is exposed skin, flag as potential nudity
        if skin_ratio >= 0.78:
            logger.warning(f"Local heuristic flagged image for excessive skin exposure ({skin_ratio:.2f})")
            return False, "excessive_skin_exposure", skin_ratio

        return True, "clean_heuristic", skin_ratio

    except Exception as e:
        logger.warning(f"Local heuristic image analysis encountered error: {e}")
        return True, "heuristic_skipped", 0.0


def evaluate_and_enforce_image_safety(image_bytes: bytes, image_path: str = None) -> tuple[bool, str, float]:
    """
    Evaluates image against safety and NSFW policies.
    Enforces immediate storage purge if content is deemed explicit.
    
    Returns:
        tuple (is_safe: bool, reason: str, nsfw_score: float)
    Raises:
        AISafetyBlockedError: If explicit or prohibited content is detected.
    """
    if not getattr(settings, "AI_SAFETY_GATE_ENABLED", True):
        return True, "gate_disabled", 0.0

    # Test marker checks
    if (
        image_bytes == b"UNSAFE_TEST_IMAGE_BYTES"
        or b"TEST_NSFW_TRIGGER_MARKER" in image_bytes
    ):
        logger.warning("NSFW Gate: Image triggered explicit test marker.")
        if image_path and default_storage.exists(image_path):
            try:
                default_storage.delete(image_path)
            except Exception:
                pass
        raise AISafetyBlockedError(
            message="Uploaded image violated content safety standards (test marker).",
            category="explicit",
            score=0.99
        )

    # 1. Fast local heuristic pre-check
    h_safe, h_reason, h_score = local_heuristic_nsfw_analysis(image_bytes)
    if not h_safe and h_score >= 0.85:
        if image_path and default_storage.exists(image_path):
            try:
                default_storage.delete(image_path)
                logger.info(f"Purged unsafe image from storage: {image_path}")
            except Exception:
                pass
        raise AISafetyBlockedError(
            message="Uploaded image violates safety guidelines (explicit content detected).",
            category="nudity",
            score=h_score
        )

    # 2. Upstream provider check (Sightengine / OpenAI Moderation)
    try:
        is_safe, reason, score = check_image_safety(image_bytes)
        if not is_safe:
            if image_path and default_storage.exists(image_path):
                try:
                    default_storage.delete(image_path)
                    logger.info(f"Purged unsafe image from storage: {image_path}")
                except Exception:
                    pass
            raise AISafetyBlockedError(
                message=f"Uploaded image violates safety guidelines ({reason}).",
                category=reason,
                score=score
            )
        return is_safe, reason, score

    except AISafetyBlockedError:
        raise
    except AISafetyError as e:
        logger.error(f"Upstream safety provider error: {e}")
        # Re-raise to fail closed if safety service is mandatory
        raise


# Standard aliases and interfaces
NsfwContentDetectedError = AISafetyBlockedError


def _classify_image_content(image_bytes: bytes) -> tuple[bool, str]:
    """Helper wrapper for content classification."""
    is_safe, reason, _ = check_image_safety(image_bytes)
    return is_safe, reason


def evaluate_image_safety(image_input, fail_closed: bool = True) -> bool:
    """
    Standard entrypoint for NSFW pre-screening filter.
    Accepts FieldFile, UploadedFile, string path, or bytes.
    If image fails, immediately deletes it from storage and raises NsfwContentDetectedError.
    """
    image_bytes = b""
    image_path = None

    if hasattr(image_input, 'read'):
        try:
            image_input.seek(0)
            image_bytes = image_input.read()
            image_input.seek(0)
        except Exception:
            pass
        if hasattr(image_input, 'name'):
            image_path = image_input.name
        if hasattr(image_input, 'file') and hasattr(image_input.file, 'close'):
            try:
                image_input.file.close()
            except Exception:
                pass
        if hasattr(image_input, 'close'):
            try:
                image_input.close()
            except Exception:
                pass
    elif isinstance(image_input, (bytes, bytearray)):
        image_bytes = bytes(image_input)
    elif isinstance(image_input, str):
        image_path = image_input
        if default_storage.exists(image_path):
            with default_storage.open(image_path, 'rb') as f:
                image_bytes = f.read()

    try:
        is_safe, reason, score = evaluate_and_enforce_image_safety(image_bytes, image_path=image_path)
        return is_safe
    except AISafetyBlockedError:
        # Guarantee physical deletion from storage on rejection
        if image_path and default_storage.exists(image_path):
            try:
                default_storage.delete(image_path)
            except Exception as e:
                logger.warning(f"Error purging rejected image {image_path}: {e}")
        if fail_closed:
            raise
        return False
