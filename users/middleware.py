from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from deep_translator import GoogleTranslator
import json

class TranslationMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return response

        language = request.user.preferred_language
        if language == 'en':
            return response

        if response.get('Content-Type') == 'application/json':
            try:
                content = json.loads(response.content)
                translated_content = self.translate_content(content, language)
                response.content = json.dumps(translated_content)
            except (json.JSONDecodeError, TypeError):
                pass  # Not a JSON response, so we don't translate it

        return response

    def translate_content(self, data, language):
        if isinstance(data, dict):
            return {key: self.translate_content(value, language) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.translate_content(item, language) for item in data]
        elif isinstance(data, str):
            import hashlib
            cache_key = f'translation:{language}:{hashlib.md5(data.encode()).hexdigest()}'
            translated_text = cache.get(cache_key)
            if not translated_text:
                try:
                    translated_text = GoogleTranslator(source='auto', target=language).translate(data)
                    cache.set(cache_key, translated_text, timeout=3600)  # Cache for 1 hour
                except Exception as e:
                    # Log the error and return the original text
                    print(f"Translation error: {e}")
                    return data
            return translated_text
        else:
            return data