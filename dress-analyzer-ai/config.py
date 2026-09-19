import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    LLM_API_KEY: str = os.getenv("LLM_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL")
    LLM_MODEL: str = os.getenv("LLM_MODEL")
    MAX_IMAGE_SIZE_MB: int = int(os.getenv("MAX_IMAGE_SIZE_MB", 5))

    APIFY_API_TOKEN: str = os.getenv("APIFY_API_TOKEN")
    APIFY_GOOGLE_ACTOR: str = os.getenv("APIFY_GOOGLE_ACTOR", "apify/google-search-scraper")

    def validate(self):
        if not self.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY not set")
        if not self.LLM_MODEL:
            raise RuntimeError("LLM_MODEL not set")
        if not self.APIFY_API_TOKEN:
            raise RuntimeError("APIFY_API_TOKEN not set")

settings = Settings()
settings.validate()