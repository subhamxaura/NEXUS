"""Deterministic finding rules. Every finding has rule_id, severity, evidence.

Rules (V1):
- high-complexity: Python CC>10 (medium) / >20 (high); TS heuristic >15 (low)
- god-file: LOC>800 (medium)
- insecure-pattern: ast hits (medium/high by rule)
- secret-hit: scanner hits (high; private-key → critical)
- missing-tests: high-risk source file without test counterpart (low)
- parse-error: file skipped (info, honest partial state)
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawFinding:
    type: str
    severity: str
    path: str
    line: int | None
    message: str
    rule_id: str
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


GOD_FILE_LOC = 800
PY_COMPLEX_MED = 10.0
PY_COMPLEX_HIGH = 20.0
TS_COMPLEX_FLAG = 15.0


def complexity_findings(path: str, language: str, complexity: float) -> list[RawFinding]:
    out: list[RawFinding] = []
    if language == "python":
        if complexity > PY_COMPLEX_HIGH:
            out.append(
                RawFinding(
                    "high-complexity",
                    "high",
                    path,
                    None,
                    f"cyclomatic complexity {complexity:g} exceeds {PY_COMPLEX_HIGH:g}",
                    "cc-python-high",
                    {"complexity": complexity},
                    0.9,
                )
            )
        elif complexity > PY_COMPLEX_MED:
            out.append(
                RawFinding(
                    "high-complexity",
                    "medium",
                    path,
                    None,
                    f"cyclomatic complexity {complexity:g} exceeds {PY_COMPLEX_MED:g}",
                    "cc-python-medium",
                    {"complexity": complexity},
                    0.9,
                )
            )
    elif complexity > TS_COMPLEX_FLAG:
        out.append(
            RawFinding(
                "high-complexity",
                "low",
                path,
                None,
                f"heuristic complexity {complexity:g} exceeds {TS_COMPLEX_FLAG:g} "
                "(tree-sitter-grade analysis unavailable)",
                "cc-ts-heuristic",
                {"complexity": complexity},
                0.5,
            )
        )
    return out


def god_file_finding(path: str, loc: int) -> RawFinding | None:
    if loc > GOD_FILE_LOC:
        return RawFinding(
            "god-file",
            "medium",
            path,
            None,
            f"{loc} lines exceeds {GOD_FILE_LOC} (consider splitting)",
            "god-file",
            {"loc": loc},
            0.8,
        )
    return None


def missing_tests_finding(path: str, risk: float) -> RawFinding | None:
    if risk >= 0.4:
        return RawFinding(
            "missing-tests",
            "low",
            path,
            None,
            f"risk {risk:.2f} with no test counterpart found",
            "missing-tests",
            {"risk": risk},
            0.6,
        )
    return None
