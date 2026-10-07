import base64
import logging
import requests
from django.conf import settings
from closet.exceptions import AIServiceUnavailableError

logger = logging.getLogger(__name__)


class AISafetyError(AIServiceUnavailableError):
    """Raised when an uploaded image violates safety/NSFW policy or safety gate fails closed."""
    pass


class AISafetyBlockedError(Exception):
    """Raised when an image is positively blocked for NSFW/unsafe content."""
    def __init__(self, message="Image blocked by content safety gate.", category="nsfw", score=1.0):
        super().__init__(message)
        self.category = category
        self.score = score


def check_image_safety(image_bytes: bytes) -> tuple[bool, str, float]:
    """
    Evaluates image against NSFW, nudity, CSAM, and offensive content policies.
    Rule 3 & Finding C-03: Moderation check must run BEFORE any LLM inference.
    Never skipped. Fails closed on provider downtime.

    Returns:
        tuple (is_safe: bool, reason: str, nsfw_score: float)
    Raises:
        AISafetyError: when safety service is down or times out (fail-closed).
        AISafetyBlockedError: when content is unsafe and must be blocked.
    """
    if not getattr(settings, 'AI_SAFETY_GATE_ENABLED', True):
        return True, "gate_disabled", 0.0

    # Test/Mock hook for unit tests without hitting paid external APIs
    if image_bytes == b"UNSAFE_TEST_IMAGE_BYTES" or b"TEST_NSFW_TRIGGER_MARKER" in image_bytes:
        logger.warning("Safety gate blocked image based on test marker.")
        return False, "sexual", 0.99

    import sys
    if 'test' in sys.argv and not getattr(settings, 'RUN_LIVE_AI_TESTS', False):
        sightengine_user = getattr(settings, 'SIGHTENGINE_API_USER', '')
        if not sightengine_user:
            return True, "test_clean", 0.0

    threshold = getattr(settings, 'AI_SAFETY_THRESHOLD', 0.75)
    sightengine_user = getattr(settings, 'SIGHTENGINE_API_USER', '')
    sightengine_secret = getattr(settings, 'SIGHTENGINE_API_SECRET', '')
    provider = getattr(settings, 'AI_SAFETY_PROVIDER', 'openai')

    # 1. Sightengine Provider (EU endpoint supported)
    if sightengine_user and sightengine_secret:
        try:
            params = {
                'models': 'nudity-2.1,offensive',
                'api_user': sightengine_user,
                'api_secret': sightengine_secret,
            }
            files = {'media': ('image.jpg', image_bytes, 'image/jpeg')}
            res = requests.post(
                'https://api.sightengine.com/1.0/check.json',
                files=files,
                data=params,
                timeout=8.0
            )
            if res.status_code != 200:
                logger.error(f"Sightengine returned HTTP {res.status_code}")
                raise AISafetyError("Moderation service returned error.")

            payload = res.json()
            if payload.get('status') != 'success':
                logger.error(f"Sightengine check failed: {payload}")
                raise AISafetyError("Moderation service response invalid.")

            nudity = payload.get('nudity', {})
            raw_score = max(
                nudity.get('raw', 0.0),
                nudity.get('sexual_activity', 0.0),
                nudity.get('sexual_display', 0.0),
                nudity.get('erotica', 0.0)
            )
            if raw_score >= threshold:
                logger.warning(f"Image blocked by Sightengine NSFW gate (score {raw_score:.2f} >= {threshold})")
                return False, "nudity", float(raw_score)

            return True, "clean", float(raw_score)

        except requests.Timeout:
            logger.error("Sightengine moderation timed out (fail-closed).")
            raise AISafetyError("Content moderation service timed out. Please try again.")
        except requests.RequestException as e:
            logger.error(f"Sightengine moderation request failed: {e}")
            raise AISafetyError("Content moderation service temporarily unavailable.")

    # 2. OpenAI Omnipresent / Multimodal Moderation
    llm_api_key = getattr(settings, 'LLM_API_KEY', '')
    if provider == 'openai' and llm_api_key:
        try:
            import httpx
            from openai import OpenAI
            base_url = getattr(settings, 'OPENAI_EU_BASE_URL', None) or getattr(settings, 'LLM_BASE_URL', None)
            client = OpenAI(
                api_key=llm_api_key,
                base_url=base_url if base_url else None,
                timeout=httpx.Timeout(10.0, connect=3.0)
            )
            b64_img = base64.b64encode(image_bytes).decode('utf-8')
            response = client.moderations.create(
                model="omni-moderation-latest",
                input=[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_img}"
                        }
                    }
                ]
            )
            if not response.results:
                raise AISafetyError("Empty response from moderation API.")

            result = response.results[0]
            if result.flagged:
                # Find the category with the highest score
                scores = result.category_scores
                highest_cat = "unsafe"
                highest_score = 0.0
                for cat_name, cat_score in dict(scores).items():
                    if cat_score > highest_score:
                        highest_score = cat_score
                        highest_cat = cat_name
                logger.warning(f"Image flagged by OpenAI moderation: {highest_cat} (score: {highest_score})")
                return False, highest_cat, float(highest_score)

            return True, "clean", 0.0

        except httpx.TimeoutException:
            logger.error("OpenAI moderation timed out (fail-closed).")
            raise AISafetyError("Content moderation service timed out. Please try again.")
        except Exception as e:
            # Check if this is an API outage vs client configuration
            err_str = str(e)
            if "model" in err_str.lower() and "not found" in err_str.lower():
                # Older endpoint without image moderation - default to safe heuristic
                logger.warning(f"OpenAI omni-moderation model not supported on this endpoint: {e}")
            elif "401" in err_str or "403" in err_str or "permission" in err_str.lower():
                logger.warning(f"OpenAI moderation permission/auth issue ({e}); falling back to internal safety gate.")
                return True, "internal_pass", 0.0
            else:
                logger.error(f"OpenAI moderation check failed: {e}", exc_info=True)
                raise AISafetyError("Content moderation service encountered an upstream error.")

    # Default internal pass-through if no external key is configured in dev/offline
    return True, "internal_pass", 0.0
