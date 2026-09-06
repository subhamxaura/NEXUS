"""OpenAI adapter (primary while user provides an OpenAI key)."""

import json
from typing import Any, cast

from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus.llm.client import LLMResult, PermanentLLMError, TokenUsage, TransientLLMError


class OpenAIClient:
    name = "openai"

    def __init__(self, api_key: str, default_model: str) -> None:
        if not api_key:
            raise PermanentLLMError("OPENAI_API_KEY is not configured")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = default_model

    @retry(
        retry=retry_if_exception_type(TransientLLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_tokens: int = 4000,
        timeout_s: int = 120,
    ) -> LLMResult:
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=cast(
                    Any, [{"role": m["role"], "content": m["content"]} for m in messages]
                ),
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                timeout=timeout_s,
            )
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            raise TransientLLMError(str(e)) from e
        except APIStatusError as e:
            if e.status_code is not None and e.status_code >= 500:
                raise TransientLLMError(str(e)) from e
            raise PermanentLLMError(str(e)) from e
        content = (resp.choices[0].message.content or "").strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise TransientLLMError(f"non-JSON model output: {e}") from e
        # NOTE: schema validation happens in BaseAgent (re-prompt on failure),
        # so the raw object is returned here without validating.
        use = resp.usage
        return LLMResult(
            data=data if isinstance(data, dict) else {"value": data},
            usage=TokenUsage(
                model=resp.model,
                prompt_tokens=use.prompt_tokens if use else 0,
                completion_tokens=use.completion_tokens if use else 0,
            ),
        )
