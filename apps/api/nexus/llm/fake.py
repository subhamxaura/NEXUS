"""Scripted LLM for tests and explicitly labeled local demo mode only.

NEVER used in production paths: the factory raises when no provider key is
configured instead of falling back to this.
"""

from pydantic import BaseModel

from nexus.llm.client import LLMResult, PermanentLLMError, TokenUsage


class FakeLLMClient:
    """Pop scripted JSON-serializable payloads per agent name.

    `scripts` maps agent name → list of payloads served in order. When a
    payload fails schema validation and `allow_reprompt` is set, the next
    payload for that agent is served as the repair attempt.
    """

    name = "fake"

    def __init__(self, scripts: dict[str, list[object]], model: str = "fake-test") -> None:
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._model = model
        self.calls: list[dict[str, object]] = []

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_tokens: int = 4000,
        timeout_s: int = 120,
    ) -> LLMResult:
        agent = "unknown"
        for m in messages:
            if m["role"] == "system" and m["content"].startswith("agent:"):
                agent = m["content"].split("\n", 1)[0].removeprefix("agent:").strip()
                break
        self.calls.append({"agent": agent, "messages": len(messages)})
        queue = self._scripts.get(agent, [])
        if not queue:
            raise PermanentLLMError(f"fake LLM has no scripted response for agent '{agent}'")
        payload = queue.pop(0)
        if not isinstance(payload, dict):
            raise PermanentLLMError(f"fake LLM payload for '{agent}' is not a JSON object")
        # NOTE: no schema validation here — BaseAgent validates and re-prompts,
        # which is exactly what the retry tests exercise.
        return LLMResult(data=payload, usage=TokenUsage(model=self._model))
