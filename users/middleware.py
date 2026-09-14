from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
import json
import logging

logger = logging.getLogger(__name__)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None
    logger.warning("deep_translator package is not installed. TranslationMiddleware will be inactive.")


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

    def translate_content(self, data, language):
        if not GoogleTranslator:
            return data

        if isinstance(data, dict):
            return {key: self.translate_content(value, language) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.translate_content(item, language) for item in data]
        elif isinstance(data, str):
            # Don't translate empty strings or very short codes/URLs/emails
            trimmed = data.strip()
            if not trimmed or len(trimmed) < 2 or '@' in trimmed or trimmed.startswith('http'):
                return data

            import hashlib
            cache_key = f'translation:{language}:{hashlib.md5(data.encode("utf-8")).hexdigest()}'
            translated_text = cache.get(cache_key)
            if not translated_text:
                try:
                    translated_text = GoogleTranslator(source='auto', target=language).translate(data)
                    cache.set(cache_key, translated_text, timeout=3600)  # Cache for 1 hour
                except Exception as e:
                    logger.warning(f"Translation error for text '{data[:30]}...': {e}")
                    return data
            return translated_text
        else:
            return data