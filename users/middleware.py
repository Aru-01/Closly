from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
import json
import logging
import hashlib
import re

logger = logging.getLogger(__name__)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None
    logger.warning("deep_translator package is not installed. TranslationMiddleware will be inactive.")


SKIP_KEYS = {
    'id', 'pk', 'uuid', 'user_id', 'sender_id', 'recipient_id', 'item_id', 'outfit_id', 'product_id',
    'token', 'access', 'refresh', 'verification_token', 'otp', 'code', 'status_code',
    'url', 'image', 'profile_picture', 'cloth_picture', 'picture', 'avatar',
    'created_at', 'updated_at', 'last_worn_at', 'date_of_birth', 'last_login', 'timestamp',
    'email', 'hex_code', 'color_code', 'skin_tone', 'color_palette',
    'password', 'confirm_password',
}

HEX_COLOR_REGEX = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
UUID_REGEX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
ISO_DATE_REGEX = re.compile(r'^\d{4}-\d{2}-\d{2}')
NUMERIC_REGEX = re.compile(r'^-?\d+(?:\.\d+)?$')


class TranslationMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if not GoogleTranslator:
            return response

        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return response

        language = getattr(request.user, 'preferred_language', 'en')
        if not language or language == 'en':
            return response

        content_type = response.get('Content-Type', '')
        if 'application/json' in content_type:
            try:
                content = json.loads(response.content.decode('utf-8'))
                translated_content = self.translate_content(content, language)
                response.content = json.dumps(translated_content).encode('utf-8')
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                logger.debug(f"TranslationMiddleware skipped non-JSON or decode error: {e}")

        return response

    def _should_skip_string(self, text):
        """Quickly determine if a string is technical/non-translatable data"""
        trimmed = text.strip()
        if not trimmed or len(trimmed) < 2:
            return True

        # Skip URLs, email addresses, file paths, and hex codes
        if '@' in trimmed or '://' in trimmed or trimmed.startswith(('http', '/', '#')):
            return True

        # Skip numbers and numeric identifiers
        if NUMERIC_REGEX.match(trimmed):
            return True

        # Skip UUIDs and ISO dates
        if UUID_REGEX.match(trimmed) or ISO_DATE_REGEX.match(trimmed):
            return True

        return False

    def translate_content(self, data, language, current_key=None):
        if not GoogleTranslator:
            return data

        if current_key and str(current_key).lower() in SKIP_KEYS:
            return data

        if isinstance(data, dict):
            return {
                key: self.translate_content(value, language, current_key=key)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self.translate_content(item, language, current_key=current_key) for item in data]
        elif isinstance(data, str):
            if self._should_skip_string(data):
                return data

            cache_key = f'translation:{language}:{hashlib.md5(data.encode("utf-8")).hexdigest()}'
            translated_text = cache.get(cache_key)
            if not translated_text:
                try:
                    translated_text = GoogleTranslator(source='auto', target=language).translate(data)
                    cache.set(cache_key, translated_text, timeout=86400)  # Cache for 24 hours
                except Exception as e:
                    logger.warning(f"Translation error for text '{data[:30]}...': {e}")
                    return data
            return translated_text
        else:
            return data


class UserActivityMiddleware(MiddlewareMixin):
    """
    Middleware to automatically record user activity and maintain real-time online status
    whenever an authenticated user interacts with any Closly API endpoint.
    """
    def process_response(self, request, response):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            try:
                from users.utils import set_user_online
                set_user_online(str(user.id))
            except Exception:
                pass
        return response