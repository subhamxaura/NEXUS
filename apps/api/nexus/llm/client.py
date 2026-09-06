"""Provider-agnostic LLM client contract."""

from typing import Any, Protocol

from pydantic import BaseModel


class TokenUsage(BaseModel):
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMResult(BaseModel):
    data: dict[str, Any]
    usage: TokenUsage = TokenUsage()


class TransientLLMError(RuntimeError):
    """Rate limits, 5xx, timeouts — safe to retry with backoff."""


class PermanentLLMError(RuntimeError):
    """Auth, bad request, missing key — do not retry."""


class LLMClient(Protocol):
    name: str

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_tokens: int = 4000,
        timeout_s: int = 120,
    ) -> LLMResult:
        """Return validated-against-`response_model` JSON (raises on failure)."""
        ...
