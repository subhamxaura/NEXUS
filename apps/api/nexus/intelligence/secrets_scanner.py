"""Secret scanning: regex patterns + Shannon entropy on long tokens.

Deterministic; findings carry the matched rule and a redacted preview only —
raw secret values are never stored in evidence.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("aws-access-key", r"AKIA[0-9A-Z]{16}", "possible AWS access key"),
    (
        "github-token",
        r"gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}",
        "possible GitHub token",
    ),
    ("private-key", r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", "private key material"),
    (
        "generic-password",
        r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}['\"]",
        "hardcoded password",
    ),
    (
        "generic-secret-assign",
        r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "hardcoded secret",
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (rule_id, re.compile(pattern), message) for rule_id, pattern, message in _PATTERNS
)

_TOKEN_RE = re.compile(r"['\"]([^'\"]{20,})['\"]")
ENTROPY_THRESHOLD = 4.5


@dataclass(frozen=True)
class SecretHit:
    line: int
    rule_id: str
    message: str


def shannon_entropy(token: str) -> float:
    if not token:
        return 0.0
    counts = Counter(token)
    length = len(token)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def scan_text(source: str) -> tuple[SecretHit, ...]:
    hits: list[SecretHit] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for rule_id, pattern, message in _COMPILED:
            if pattern.search(line):
                hits.append(SecretHit(lineno, rule_id, message))
        for token_match in _TOKEN_RE.finditer(line):
            token = token_match.group(1)
            if len(token) >= 20 and shannon_entropy(token) >= ENTROPY_THRESHOLD:
                # Skip tokens already caught by a pattern on this line.
                if not any(h.line == lineno for h in hits):
                    hits.append(
                        SecretHit(
                            lineno, "high-entropy-string", "high-entropy string resembles a secret"
                        )
                    )
                break
    return tuple(hits)
