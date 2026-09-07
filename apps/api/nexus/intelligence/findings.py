"""Deterministic finding rules. Every finding has rule_id, severity, evidence.

Rules (V1):
- high-complexity: Python CC>10 (medium) / >20 (high); TS heuristic >15 (low);
  C/C++ heuristic >15 (low)
- god-file: LOC>800 (medium)
- insecure-pattern: ast hits (medium/high by rule); C heuristic hits
  (c-gets high, c-missing-free low, other c-* medium)
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
C_COMPLEX_FLAG = 15.0


@dataclass(frozen=True)
class RuleGuidance:
    why: str
    fix: str


RULE_GUIDANCE: dict[str, RuleGuidance] = {
    "cc-python-high": RuleGuidance(
        why="Very high branching makes the function hard to test and likely to hide bugs.",
        fix="Extract helper functions for each branch group; add tests per branch.",
    ),
    "cc-python-medium": RuleGuidance(
        why="Above-average branching raises the cost of review and testing.",
        fix="Split the largest branch block into a named helper with its own test.",
    ),
    "cc-ts-heuristic": RuleGuidance(
        why="Keyword heuristic suggests dense branching (tree-sitter unavailable).",
        fix="Manually review the flagged file; split complex functions.",
    ),
    "cc-c-heuristic": RuleGuidance(
        why="Token heuristic suggests dense branching in C/C++ code.",
        fix="Split complex functions; prefer early returns and small helpers.",
    ),
    "god-file": RuleGuidance(
        why="Oversized files slow navigation, review, and ownership.",
        fix="Split by responsibility into focused modules behind a thin facade.",
    ),
    "missing-tests": RuleGuidance(
        why="High-risk code without tests fails silently on the next change.",
        fix="Add a test file covering the riskiest function first.",
    ),
    "py-eval-exec": RuleGuidance(
        why="Executes arbitrary code from input data — a direct code-execution vector.",
        fix="Replace with ast.literal_eval or an explicit allow-listed dispatch table.",
    ),
    "py-pickle": RuleGuidance(
        why="Unpickling untrusted data can execute arbitrary code on load.",
        fix="Use JSON or another safe serialization format; never unpickle untrusted bytes.",
    ),
    "py-yaml-load": RuleGuidance(
        why="yaml.load with the default Loader can construct arbitrary objects.",
        fix="Use yaml.safe_load.",
    ),
    "py-os-system": RuleGuidance(
        why="Passes commands through a shell, inviting command injection.",
        fix="Use subprocess.run with an argument list and shell=False.",
    ),
    "py-subprocess-shell": RuleGuidance(
        why="shell=True with variable input allows shell injection.",
        fix="Pass an argument list with shell=False; validate inputs.",
    ),
    "c-gets": RuleGuidance(
        why="gets() performs unbounded input into a fixed buffer — always exploitable.",
        fix="Replace with fgets() and an explicit buffer size.",
    ),
    "c-strcpy": RuleGuidance(
        why="Unbounded copy can overflow the destination buffer.",
        fix="Use a bounded copy with an explicit size, or a safe string API.",
    ),
    "c-strcat": RuleGuidance(
        why="Unbounded concatenation can overflow the destination buffer.",
        fix="Track remaining capacity or use a bounded append.",
    ),
    "c-sprintf": RuleGuidance(
        why="Unbounded formatting can overflow the destination buffer.",
        fix="Use snprintf() with an explicit size and check its return.",
    ),
    "c-system": RuleGuidance(
        why="Passes commands through a shell, inviting command injection.",
        fix="Avoid with variable input; prefer exec-family calls with argument lists.",
    ),
    "c-popen": RuleGuidance(
        why="Passes commands through a shell, inviting command injection.",
        fix="Avoid with variable input; prefer pipes with exec-family calls.",
    ),
    "c-scanf-unbounded": RuleGuidance(
        why="Unbounded %s conversion can overflow the destination buffer.",
        fix="Add an explicit field width such as %63s for a 64-byte buffer.",
    ),
    "c-missing-free": RuleGuidance(
        why="Heap allocations without a matching free() suggest a leak.",
        fix="Confirm ownership and lifetime; free every path or use a clear owner.",
    ),
    "secret-aws-access-key": RuleGuidance(
        why="A leaked access key grants account access until rotated.",
        fix="Revoke the key immediately, purge it from history, use a secrets manager.",
    ),
    "secret-github-token": RuleGuidance(
        why="A leaked token grants repository/API access until revoked.",
        fix="Revoke the token, purge from history, use minimal scopes or OIDC.",
    ),
    "secret-private-key": RuleGuidance(
        why="Private key material must never live in source control.",
        fix="Remove it, rotate the keypair, store keys in a dedicated secret store.",
    ),
    "secret-generic-password": RuleGuidance(
        why="Hardcoded passwords leak to every clone and log.",
        fix="Move to environment variables or a secrets manager.",
    ),
    "secret-generic-secret-assign": RuleGuidance(
        why="Hardcoded secrets leak to every clone and log.",
        fix="Move to environment variables or a secrets manager; rotate the value.",
    ),
    "secret-high-entropy-string": RuleGuidance(
        why="High-entropy strings often turn out to be keys or tokens.",
        fix="Confirm what it is; if sensitive, rotate and move to a secrets manager.",
    ),
    "parse-error": RuleGuidance(
        why="The file could not be parsed, so its metrics are missing.",
        fix="Fix the syntax error or exclude generated files from analysis.",
    ),
}


def guidance_for(rule_id: str) -> RuleGuidance | None:
    return RULE_GUIDANCE.get(rule_id)


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
    elif language in ("javascript", "typescript"):
        if complexity > TS_COMPLEX_FLAG:
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
    elif language in ("c", "cpp"):
        if complexity > C_COMPLEX_FLAG:
            out.append(
                RawFinding(
                    "high-complexity",
                    "low",
                    path,
                    None,
                    f"heuristic complexity {complexity:g} exceeds {C_COMPLEX_FLAG:g} "
                    "(heuristic-c-v1)",
                    "cc-c-heuristic",
                    {"complexity": complexity},
                    0.6,
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
