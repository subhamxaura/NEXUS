"""Base agent: schema-validated I/O, budgeted retries, re-prompt on validation errors."""

from abc import ABC
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from nexus.agents.context import AgentContext
from nexus.llm.client import LLMClient, PermanentLLMError, TokenUsage, TransientLLMError

PROMPT_DIR = Path(__file__).parent / "prompts"

# Retry policy: transient LLM failures ≤3 attempts w/ backoff; schema failures
# get one re-prompt carrying the validation error, then fail visibly.
MAX_ATTEMPTS = 3


class AgentFailure(RuntimeError):
    pass


class BaseAgent(ABC):
    name: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    prompt_file: str = ""
    prompt_version: str = "v1"

    def load_prompt(self) -> str:
        if not self.prompt_file:
            return ""
        return (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")

    def build_messages(self, data: BaseModel) -> list[dict[str, str]]:
        system = f"agent:{self.name}\n{self.load_prompt()}".strip()
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": data.model_dump_json()},
        ]

    async def run(self, ctx: AgentContext, data: BaseModel) -> tuple[BaseModel, TokenUsage, int]:
        """Returns (validated output, token usage, attempts). Raises AgentFailure."""
        validated_input = self.input_schema.model_validate(data.model_dump())
        messages = self.build_messages(validated_input)
        usage = TokenUsage()
        last_error = ""
        attempts = 0
        backoff_s = 1.0
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            await ctx.emit(
                "retrying" if attempts > 1 else "started", {"agent": self.name, "attempt": attempts}
            )
            try:
                result = await self._call(ctx.llm, messages, ctx)
            except TransientLLMError as e:
                last_error = str(e)
                await ctx.emit("retrying", {"agent": self.name, "error": last_error})
                await _asleep(min(backoff_s, 8.0))
                backoff_s *= 2
                continue
            except PermanentLLMError as e:
                raise AgentFailure(f"{self.name}: {e}") from e
            usage.prompt_tokens += result.usage.prompt_tokens
            usage.completion_tokens += result.usage.completion_tokens
            if not usage.model:
                usage.model = result.usage.model
            try:
                output = self.output_schema.model_validate(result.data)
            except ValidationError as e:
                last_error = f"schema validation failed: {e}"
                await ctx.emit("retrying", {"agent": self.name, "error": last_error})
                messages = messages + [
                    {
                        "role": "user",
                        "content": f"Your previous output failed validation:\n{last_error}\n"
                        f"Reply with corrected JSON only.",
                    }
                ]
                continue
            await ctx.emit("completed", {"agent": self.name, "attempts": attempts})
            return output, usage, attempts
        raise AgentFailure(f"{self.name} failed after {attempts} attempts: {last_error}")

    async def _call(self, llm: LLMClient, messages: list[dict[str, str]], ctx: AgentContext) -> Any:
        return await llm.complete_json(
            messages,
            self.output_schema,
            max_tokens=ctx.max_tokens,
            timeout_s=ctx.timeout_s,
        )


async def _asleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
