# LLM client + provider-agnostic setup
from openai import OpenAI
from config import settings

def get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None
    )

llm_client = get_llm_client()
