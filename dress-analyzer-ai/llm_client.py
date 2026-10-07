# LLM client + provider-agnostic setup
import httpx
from openai import OpenAI
from config import settings


def get_llm_client() -> OpenAI:
    api_key = settings.LLM_API_KEY
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not configured.")
    return OpenAI(
        api_key=api_key,
        base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
        timeout=httpx.Timeout(30.0, connect=5.0),
        max_retries=1
    )


class LazyLLMClientProxy:
    """Proxies OpenAI client calls lazily to avoid import-time crashes when API keys are unset."""
    def __getattr__(self, name):
        client = get_llm_client()
        return getattr(client, name)


llm_client = LazyLLMClientProxy()

