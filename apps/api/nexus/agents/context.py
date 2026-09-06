"""Permission-scoped agent context. No unrestricted shell/network/secret access."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nexus.llm.client import LLMClient

EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class AgentContext:
    mission_id: int
    workspace: Path
    llm: LLMClient
    emit: EventEmitter
    max_tokens: int = 4000
    timeout_s: int = 120
    extra: dict[str, Any] = field(default_factory=dict)

    def read_file(self, rel_path: str, limit_chars: int = 12000) -> str:
        """Read a repo-relative file, truncated with an explicit marker."""
        normalized = str(Path(rel_path).as_posix())
        if normalized.startswith("..") or normalized.startswith("/") or normalized == ".":
            raise ValueError(f"invalid path: {rel_path}")
        data = (self.workspace / normalized).read_bytes()[:limit_chars]
        text = data.decode("utf-8", errors="replace")
        if len(data) >= limit_chars:
            text += "\n[... truncated ...]"
        return text

    def search_code(self, pattern: str, limit: int = 20) -> list[str]:
        """Regex search over supported source files. Returns path:line matches."""
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"invalid pattern: {e}") from e
        hits: list[str] = []
        for path in sorted(self.workspace.rglob("*")):
            if len(hits) >= limit:
                break
            if not path.is_file() or path.suffix.lower() not in (
                ".py",
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
            ):
                continue
            if ".git" in path.parts or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    hits.append(f"{path.relative_to(self.workspace).as_posix()}:{lineno}")
                    if len(hits) >= limit:
                        break
        return hits
