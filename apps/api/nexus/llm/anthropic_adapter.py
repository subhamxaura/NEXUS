"""Anthropic adapter (spec default; active when provider=anthropic + key set)."""

import json

from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus.llm.client import LLMResult, PermanentLLMError, TokenUsage, TransientLLMError


class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str, default_model: str) -> None:
        if not api_key:
            raise PermanentLLMError("ANTHROPIC_API_KEY is not configured")
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
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
        from anthropic import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        schema = response_model.model_json_schema()
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [
            {"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"
        ]
        if not rest:
            raise PermanentLLMError("no user message provided")
        prompt = (
            "Respond with a single JSON object matching this schema, no other text:\n"
            f"{json.dumps(schema)}"
        )
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=f"{system}\n{prompt}" if system else prompt,
                messages=rest,  # type: ignore[arg-type]
                timeout=timeout_s,
            )
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            raise TransientLLMError(str(e)) from e
        except APIStatusError as e:
            if e.status_code is not None and e.status_code >= 500:
                raise TransientLLMError(str(e)) from e
            raise PermanentLLMError(str(e)) from e
        content = "".join(b.text for b in resp.content if b.type == "text").strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise TransientLLMError(f"non-JSON model output: {e}") from e
        # NOTE: schema validation happens in BaseAgent (re-prompt on failure),
        # so the raw object is returned here without validating.
        return LLMResult(
            data=data if isinstance(data, dict) else {"value": data},
            usage=TokenUsage(
                model=resp.model,
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
            ),
        )
