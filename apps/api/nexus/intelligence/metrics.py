"""Metrics: LOC, cyclomatic complexity, maintainability, test-presence proxy.

- Python: radon for complexity + MI (spec stack). Unparseable files get
  complexity 0 and `parse_error` recorded — never fabricated.
- TS/JS: documented keyword heuristic (tree-sitter deferred). The
  `complexity_source` field always says which method produced the number.
"""

import re
from dataclasses import dataclass

_TS_BRANCH_RE = re.compile(r"\b(if|for|while|case|catch|elif|else\s+if)\b|&&|\|\||\?(?![?.:])")

_HEURISTIC_SCALE = 1.0


@dataclass(frozen=True)
class FileNumbers:
    loc: int
    complexity: float
    maintainability: float | None
    complexity_source: str
    parse_error: str | None = None


def loc_of(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip())


def python_numbers(source: str) -> FileNumbers:
    from radon.complexity import cc_visit  # lazy: keeps import cost off for TS-only repos
    from radon.raw import analyze

    raw = analyze(source)
    loc = raw.sloc
    try:
        blocks = cc_visit(source)
    except Exception:
        return FileNumbers(
            loc=loc,
            complexity=0.0,
            maintainability=None,
            complexity_source="radon",
            parse_error="unparseable",
        )
    complexity = float(sum(b.complexity for b in blocks)) if blocks else 1.0
    try:
        from radon.visitors import h_visit

        mi = float(h_visit(source).total.mi)
    except Exception:
        mi = None
    return FileNumbers(
        loc=loc, complexity=complexity, maintainability=mi, complexity_source="radon"
    )


def ts_numbers(source: str) -> FileNumbers:
    branches = len(_TS_BRANCH_RE.findall(source))
    functions = len(re.findall(r"\bfunction\b|=>", source)) or 1
    complexity = round((1 + branches / max(functions, 1)) * _HEURISTIC_SCALE, 2)
    return FileNumbers(
        loc=loc_of(source),
        complexity=complexity,
        maintainability=None,
        complexity_source="heuristic-ts-v1",
    )
