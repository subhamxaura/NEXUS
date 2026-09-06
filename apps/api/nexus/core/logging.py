"""Structured logging with secret redaction. Never log tokens/keys/headers."""

import logging
import re

_PATTERNS = [
    # "Authorization: Bearer <tok>" / "authorization=bearer <tok>" → whole value
    re.compile(r"(?i)authorization\s*[:=]\s*(bearer\s+)?\S+"),
    re.compile(
        r"(?i)(github_token|api[_-]?key|client_secret|private_key|secret|passwd)\s*[:=]\s*\S+"
    ),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    out = text
    for p in _PATTERNS:
        out = p.sub(REDACTED, out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            redacted: list[object] = []
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            for a in args:
                redacted.append(redact(a) if isinstance(a, str) else a)
            record.args = tuple(redacted)
        return True


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logging.basicConfig(
        level=level, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    return logging.getLogger("nexus")
