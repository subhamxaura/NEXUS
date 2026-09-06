"""Client factory. Truthful failure when no key is configured — never a fake."""

from nexus.core.config import settings
from nexus.llm.anthropic_adapter import AnthropicClient
from nexus.llm.client import LLMClient, PermanentLLMError
from nexus.llm.openai_adapter import OpenAIClient


def get_client() -> LLMClient:
    provider = settings.llm_provider.lower()
    model = getattr(settings, "llm_default_model", "gpt-4o-mini")
    if provider == "openai":
        return OpenAIClient(api_key=getattr(settings, "openai_api_key", ""), default_model=model)
    if provider == "anthropic":
        return AnthropicClient(
            api_key=getattr(settings, "anthropic_api_key", ""), default_model=model
        )
    raise PermanentLLMError(f"unknown LLM provider '{settings.llm_provider}'")
