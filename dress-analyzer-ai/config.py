import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    @property
    def LLM_API_KEY(self) -> str:
        try:
            from django.conf import settings as dj_settings
            key = getattr(dj_settings, 'LLM_API_KEY', None)
            if key:
                return str(key).strip()
        except Exception:
            pass
        return os.getenv("LLM_API_KEY", "").strip()

    @property
    def LLM_BASE_URL(self) -> str | None:
        try:
            from django.conf import settings as dj_settings
            url = getattr(dj_settings, 'LLM_BASE_URL', None)
            if url:
                return str(url).strip()
        except Exception:
            pass
        val = os.getenv("LLM_BASE_URL")
        return val.strip() if val else None

    @property
    def LLM_MODEL(self) -> str:
        try:
            from django.conf import settings as dj_settings
            model = getattr(dj_settings, 'LLM_MODEL', None)
            if model:
                return str(model).strip()
        except Exception:
            pass
        return os.getenv("LLM_MODEL", "gpt-4o").strip()

    @property
    def MAX_IMAGE_SIZE_MB(self) -> int:
        try:
            from django.conf import settings as dj_settings
            mb = getattr(dj_settings, 'MAX_IMAGE_SIZE_MB', None)
            if mb is not None:
                return int(mb)
        except Exception:
            pass
        return int(os.getenv("MAX_IMAGE_SIZE_MB", 5))

    @property
    def AI_BRAND_SEARCH_ENABLED(self) -> bool:
        try:
            from django.conf import settings as dj_settings
            enabled = getattr(dj_settings, 'AI_BRAND_SEARCH_ENABLED', None)
            if enabled is not None:
                return bool(enabled)
        except Exception:
            pass
        return os.getenv("AI_BRAND_SEARCH_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def APIFY_API_TOKEN(self) -> str:
        try:
            from django.conf import settings as dj_settings
            token = getattr(dj_settings, 'APIFY_API_TOKEN', None)
            if token:
                return str(token).strip()
        except Exception:
            pass
        return os.getenv("APIFY_API_TOKEN", "").strip()

    @property
    def APIFY_GOOGLE_ACTOR(self) -> str:
        try:
            from django.conf import settings as dj_settings
            actor = getattr(dj_settings, 'APIFY_GOOGLE_ACTOR', None)
            if actor:
                return str(actor).strip()
        except Exception:
            pass
        return os.getenv("APIFY_GOOGLE_ACTOR", "apify/google-search-scraper").strip()

    def validate(self):
        if not self.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY not set")
        if not self.LLM_MODEL:
            raise RuntimeError("LLM_MODEL not set")


settings = Settings()