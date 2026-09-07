"""Analysis pipeline: walk → parse → graph → score → findings. Fully deterministic."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus.intelligence import graph as dep_graph
from nexus.intelligence.c_parser import parse_c, resolve_c_include
from nexus.intelligence.churn import batch_churn
from nexus.intelligence.detector import SKIP_DIRS, detect_language
from nexus.intelligence.findings import (
    RawFinding,
    complexity_findings,
    god_file_finding,
    missing_tests_finding,
)
from nexus.intelligence.metrics import c_numbers, python_numbers, ts_numbers
from nexus.intelligence.python_parser import parse_python
from nexus.intelligence.scoring import file_risk, finding_priority, health_score
from nexus.intelligence.secrets_scanner import SecretHit, scan_text
from nexus.intelligence.ts_parser import resolve_relative_import

MAX_FILES = 2000
MAX_FILE_BYTES = 1_000_000

_HIGH_INSECURE_RULES = frozenset({"py-eval-exec", "py-pickle", "c-gets"})
_LOW_INSECURE_RULES = frozenset({"c-missing-free"})


@dataclass(frozen=True)
class ScoredFinding:
    type: str
    severity: str
    path: str
    line: int | None
    message: str
    rule_id: str
    evidence: dict[str, Any]
    priority: float


@dataclass(frozen=True)
class FileResult:
    path: str
    language: str
    loc: int
    complexity: float
    maintainability: float | None
    churn: int
    test_presence: float
    risk: float
    risk_contributors: dict[str, float]
    in_degree: int
    out_degree: int


@dataclass(frozen=True)
class PipelineResult:
    files: tuple[FileResult, ...]
    edges: tuple[tuple[str, str, str], ...]
    findings: tuple[ScoredFinding, ...]
    health: float
    health_breakdown: dict[str, float]
    availability: dict[str, str]
    skipped: tuple[str, ...]
    file_count: int


def _walk(repo_dir: Path) -> list[str]:
    collected: list[str] = []
    for root, dirs, names in os.walk(repo_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            full = Path(root) / name
            rel = full.relative_to(repo_dir).as_posix()
            collected.append(rel)
            if len(collected) >= MAX_FILES * 2:  # hard stop before filtering
                return collected
    return collected


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    stem = lowered.rsplit("/", 1)[-1]
    return (
        stem.startswith("test_")
        or stem.startswith("tests_")
        or stem.endswith("_test.py")
        or stem.endswith(".test.ts")
        or stem.endswith(".test.tsx")
        or stem.endswith(".test.js")
        or stem.endswith(".spec.ts")
        or stem.endswith(".spec.js")
        or stem.endswith("_test")
        or lowered.startswith(("tests/", "test/"))
        or "/tests/" in lowered
        or "/test/" in lowered
        or "/__tests__/" in lowered
    )


def _resolve_python_import(spec: str, src_path: str, files: frozenset[str]) -> str | None:
    if spec.startswith("."):
        level = len(spec) - len(spec.lstrip("."))
        rest = spec.lstrip(".")
        pkg_parts = src_path.split("/")[:-1]
        base_parts = pkg_parts[: max(0, len(pkg_parts) - level + 1)]
        dotted = (base_parts + rest.split(".")) if rest else base_parts
    else:
        dotted = spec.split(".")
    rel = "/".join(dotted)
    for cand in (rel + ".py", rel + "/__init__.py"):
        if cand in files:
            return cand
    return None


def _test_proxy(path: str, test_stems: frozenset[str]) -> float:
    if _is_test_path(path):
        return 1.0
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return 1.0 if stem in test_stems else 0.0


def run_pipeline(repo_dir: Path) -> PipelineResult:
    rel_paths = _walk(repo_dir)
    supported: dict[str, str] = {}
    skipped: list[str] = []
    for rel in rel_paths:
        lang = detect_language(rel)
        if lang is None:
            continue
        full = repo_dir / rel
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            supported[rel] = lang
        except OSError:
            skipped.append(rel)
            continue
        if len(supported) >= MAX_FILES:
            skipped.extend(r for r in rel_paths if detect_language(r) and r not in supported)
            break

    file_set = frozenset(supported)
    sources: dict[str, str] = {}
    parse_errors: dict[str, str] = {}
    for rel in sorted(supported):
        try:
            text = (repo_dir / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(rel)
            continue
        sources[rel] = text

    imports: dict[str, list[str]] = {}
    insecure: dict[str, list[dict[str, Any]]] = {}
    secrets: dict[str, tuple[SecretHit, ...]] = {}
    numbers: dict[str, tuple[int, float, float | None]] = {}
    for rel in sorted(sources):
        lang = supported[rel]
        text = sources[rel]
        if lang == "python":
            py_facts = parse_python(text)
            if py_facts.parse_error:
                parse_errors[rel] = py_facts.parse_error
            imports[rel] = list(py_facts.imports)
            insecure[rel] = [
                {"line": h.line, "rule_id": h.rule_id, "message": h.message}
                for h in py_facts.insecure
            ]
            nums = python_numbers(text)
        elif lang in ("c", "cpp"):
            c_facts = parse_c(text)
            if c_facts.parse_error:
                parse_errors[rel] = c_facts.parse_error
            imports[rel] = list(c_facts.includes)
            insecure[rel] = [
                {"line": h.line, "rule_id": h.rule_id, "message": h.message}
                for h in c_facts.insecure
            ]
            nums = c_numbers(text, len(c_facts.functions))
        else:
            from nexus.intelligence.ts_parser import parse_ts

            ts_facts = parse_ts(text)
            imports[rel] = list(ts_facts.imports)
            insecure[rel] = []
            nums = ts_numbers(text)
        numbers[rel] = (nums.loc, nums.complexity, nums.maintainability)
        secrets[rel] = scan_text(text)

    edge_list: list[tuple[str, str, str]] = []
    for rel in sorted(sources):
        lang = supported[rel]
        for spec in sorted(set(imports[rel])):
            if lang == "python":
                dst = _resolve_python_import(spec, rel, file_set)
                kind = "import"
            elif lang in ("c", "cpp"):
                dst = resolve_c_include(rel, spec, file_set)
                kind = "include"
            else:
                dst = resolve_relative_import(rel, spec, file_set)
                kind = "import"
            if dst and dst != rel:
                edge_list.append((rel, dst, kind))

    graph = dep_graph.build_graph(sorted(sources), [(s, d) for s, d, _ in edge_list])
    deg = dep_graph.degrees(graph)
    cent = dep_graph.centrality(graph)

    churn_map = batch_churn(repo_dir, sorted(sources))
    test_stems = frozenset(
        p.rsplit("/", 1)[-1].rsplit(".", 1)[0].removesuffix("_test").removesuffix(".test")
        for p in sources
        if _is_test_path(p)
    )

    file_results: list[FileResult] = []
    risk_map: dict[str, float] = {}
    for rel in sorted(sources):
        loc, cc, mi = numbers[rel]
        sec_signal = 1.0 if (insecure[rel] or secrets[rel]) else 0.0
        proxy = _test_proxy(rel, test_stems)
        breakdown = file_risk(cc, churn_map.get(rel, 0), cent.get(rel, 0.0), sec_signal, proxy)
        in_d, out_d = deg.get(rel, (0, 0))
        risk_map[rel] = breakdown.risk
        file_results.append(
            FileResult(
                path=rel,
                language=supported[rel],
                loc=loc,
                complexity=cc,
                maintainability=mi,
                churn=churn_map.get(rel, 0),
                test_presence=proxy,
                risk=breakdown.risk,
                risk_contributors=breakdown.contributors,
                in_degree=in_d,
                out_degree=out_d,
            )
        )

    raw: list[RawFinding] = []
    for rel in sorted(sources):
        loc, cc, _ = numbers[rel]
        is_test = _is_test_path(rel)
        if not is_test:
            # Complexity/size rules target production code; tests are
            # branchy by nature and would only add noise.
            raw.extend(complexity_findings(rel, supported[rel], cc))
            god = god_file_finding(rel, loc)
            if god:
                raw.append(god)
        for hit in insecure[rel]:
            if hit["rule_id"] in _HIGH_INSECURE_RULES:
                sev = "high"
            elif hit["rule_id"] in _LOW_INSECURE_RULES:
                sev = "low"
            else:
                sev = "medium"
            raw.append(
                RawFinding(
                    "insecure-pattern",
                    sev,
                    rel,
                    hit["line"],
                    hit["message"],
                    hit["rule_id"],
                    {"line": hit["line"]},
                    0.9,
                )
            )
        for secret_hit in secrets[rel]:
            sev = "critical" if secret_hit.rule_id == "private-key" else "high"
            raw.append(
                RawFinding(
                    "secret-hit",
                    sev,
                    rel,
                    secret_hit.line,
                    secret_hit.message,
                    f"secret-{secret_hit.rule_id}",
                    {"line": secret_hit.line},
                    0.85,
                )
            )
        if not is_test:
            mt = missing_tests_finding(rel, risk_map[rel])
            if mt:
                raw.append(mt)
    for rel, err in sorted(parse_errors.items()):
        raw.append(
            RawFinding(
                "parse-error",
                "info",
                rel,
                None,
                f"file skipped from metrics: {err}",
                "parse-error",
                {"error": err},
                1.0,
            )
        )

    scored: list[ScoredFinding] = []
    for f in raw:
        reach = min(1.0, (1 + len(dep_graph.dependents(graph, f.path))) / 6.0)
        scored.append(
            ScoredFinding(
                type=f.type,
                severity=f.severity,
                path=f.path,
                line=f.line,
                message=f.message,
                rule_id=f.rule_id,
                evidence=f.evidence,
                priority=finding_priority(
                    f.severity, f.confidence, risk_map.get(f.path, 0.0), reach
                ),
            )
        )
    scored.sort(key=lambda s: (-s.priority, s.path, s.rule_id))

    sec_count = sum(
        1 for f in scored if f.severity in ("critical", "high") and f.type != "missing-tests"
    )
    src_files = [fr for fr in file_results if not _is_test_path(fr.path)]
    untested = sum(1 for fr in src_files if fr.test_presence < 1.0) / max(1, len(src_files))
    hotspots = sum(1 for fr in file_results if fr.risk >= 0.5) / max(1, len(file_results))
    avg_cc = sum(fr.complexity for fr in file_results) / max(1, len(file_results))
    # Zero analyzed files is not a healthy project: mark partial so the
    # service layer persists a partial status and the health score stays 0.
    partial = bool(skipped) or bool(parse_errors) or len(file_results) == 0
    health = health_score(avg_cc, sec_count, untested, hotspots, len(file_results), partial)

    availability = {
        "radon": "available",
        "tree-sitter": "deferred (TS heuristic in use)",
        "c-cpp": "available (heuristic-c-v1)",
        "bandit": "unavailable (builtin pattern rules in use)",
        "semgrep": "unavailable (builtin pattern rules in use)",
        "dependency-audit": "unavailable (Phase 1)",
    }

    return PipelineResult(
        files=tuple(file_results),
        edges=tuple(sorted(set(edge_list))),
        findings=tuple(scored),
        health=health.score,
        health_breakdown=health.breakdown,
        availability=availability,
        skipped=tuple(sorted(set(skipped))),
        file_count=len(file_results),
    )
