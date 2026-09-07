"""C/C++ intelligence tests: detector, parser, includes, findings, pipeline.

Existing Python/JS/TS behavior is asserted unchanged alongside the new
C/C++ paths (scope: no regressions).
"""

from pathlib import Path

import pytest

from nexus.intelligence.c_parser import c_branch_count, parse_c, resolve_c_include
from nexus.intelligence.detector import detect_language
from nexus.intelligence.findings import complexity_findings, guidance_for
from nexus.intelligence.metrics import c_numbers
from nexus.intelligence.pipeline import run_pipeline
from nexus.intelligence.scoring import health_score

FIXTURE = Path(__file__).parent / "fixtures" / "sample_c_repo"


def test_detector_recognizes_c_cpp() -> None:
    assert detect_language("graph.c") == "c"
    assert detect_language("graph.h") == "c"
    assert detect_language("algo.cpp") == "cpp"
    assert detect_language("a.cc") == "cpp"
    assert detect_language("a.cxx") == "cpp"
    assert detect_language("a.hpp") == "cpp"
    assert detect_language("a.hh") == "cpp"
    assert detect_language("a.hxx") == "cpp"
    assert detect_language("SRC/MAIN.C") == "c"


def test_detector_existing_languages_unchanged() -> None:
    assert detect_language("a.py") == "python"
    assert detect_language("a.js") == "javascript"
    assert detect_language("a.jsx") == "javascript"
    assert detect_language("a.ts") == "typescript"
    assert detect_language("a.tsx") == "typescript"
    assert detect_language("notes.md") is None
    assert detect_language("main.go") is None


def test_c_parser_metrics() -> None:
    text = (FIXTURE / "graph.c").read_text()
    facts = parse_c(text)
    assert set(facts.functions) == {"graph_add", "graph_free", "graph_classify", "graph_label"}
    assert facts.includes == ("graph.h",)
    assert facts.parse_error is None
    nums = c_numbers(text, len(facts.functions))
    assert nums.loc > 0
    assert nums.complexity == len(facts.functions) + c_branch_count(text)
    assert nums.complexity == 18.0
    assert c_branch_count(text) == 14
    assert nums.complexity_source == "heuristic-c-v1"
    assert nums.maintainability is not None and 0.0 <= nums.maintainability <= 100.0


def test_c_parser_malformed_never_crashes() -> None:
    for bad in (
        "int foo( { /* unclosed comment \n int x = gets(buf); ",
        'char *s = "unclosed string; \n int main( { ',
        "#include \x00\x01 binary \xff junk ((((((",
        "",
        "///////\n******\n",
    ):
        facts = parse_c(bad)
        assert isinstance(facts.functions, tuple)
        assert isinstance(facts.includes, tuple)
        nums = c_numbers(bad, len(facts.functions))
        assert nums.complexity >= 1.0


def test_c_include_resolution() -> None:
    files = frozenset({"main.c", "graph.h", "sub/util.h", "algo.cpp", "algo.h"})
    assert resolve_c_include("main.c", "graph.h", files) == "graph.h"
    assert resolve_c_include("sub/x.c", "util.h", files) == "sub/util.h"
    assert resolve_c_include("main.c", "stdio.h", files) is None  # system header
    assert resolve_c_include("main.c", "missing.h", files) is None
    assert resolve_c_include("main.c", "/abs.h", files) is None
    assert resolve_c_include("main.c", "../escape.h", files) is None
    assert resolve_c_include("algo.cpp", "algo.h", files) == "algo.h"
    assert resolve_c_include("graph.h", "graph.h", files) is None  # self


def test_c_security_patterns() -> None:
    text = (FIXTURE / "main.c").read_text()
    hits = {h.rule_id: h for h in parse_c(text).insecure}
    assert set(hits) == {"c-scanf-unbounded", "c-system", "c-missing-free"}
    assert hits["c-scanf-unbounded"].line == 9
    cpp_hits = {h.rule_id for h in parse_c((FIXTURE / "algo.cpp").read_text()).insecure}
    assert cpp_hits == {"c-gets"}
    c_hits = {h.rule_id for h in parse_c((FIXTURE / "graph.c").read_text()).insecure}
    assert c_hits == {"c-strcpy"}
    # Commented-out calls must not fire.
    commented = parse_c("// strcpy(dst, src);\n/* system(x); */\nint f(void) {\n}\n")
    assert commented.insecure == ()


def test_c_complexity_findings_branch() -> None:
    low = complexity_findings("a.c", "c", 19.0)
    assert len(low) == 1 and low[0].rule_id == "cc-c-heuristic" and low[0].severity == "low"
    assert complexity_findings("a.cpp", "cpp", 5.0) == []
    assert complexity_findings("a.c", "c", 15.0) == []
    # Existing languages byte-identical behavior.
    py = complexity_findings("a.py", "python", 25.0)
    assert len(py) == 1 and py[0].rule_id == "cc-python-high"
    ts = complexity_findings("a.ts", "typescript", 16.0)
    assert len(ts) == 1 and ts[0].rule_id == "cc-ts-heuristic"
    assert guidance_for("c-gets") is not None
    assert guidance_for("c-missing-free") is not None
    assert guidance_for("cc-c-heuristic") is not None


def test_c_pipeline_end_to_end() -> None:
    res = run_pipeline(FIXTURE)
    assert res.file_count == 5
    assert {f.language for f in res.files} == {"c", "cpp"}
    assert {f.path for f in res.files} == {"graph.h", "graph.c", "main.c", "algo.h", "algo.cpp"}
    assert set(res.edges) == {
        ("algo.cpp", "algo.h", "include"),
        ("graph.c", "graph.h", "include"),
        ("main.c", "algo.h", "include"),
        ("main.c", "graph.h", "include"),
    }
    rules = {f.rule_id for f in res.findings}
    assert {
        "c-gets",
        "c-strcpy",
        "c-system",
        "c-scanf-unbounded",
        "c-missing-free",
        "cc-c-heuristic",
    } <= rules
    assert res.health < 100.0
    assert res == run_pipeline(FIXTURE)  # deterministic


def test_empty_repo_honest_result(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# nothing supported here\n")
    (tmp_path / "main.go").write_text("package main\n")
    res = run_pipeline(tmp_path)
    assert res.file_count == 0
    assert res.health == 0.0
    assert res.health_breakdown == {"no_supported_files": 100.0}


def test_empty_health_score_direct() -> None:
    score = health_score(0.0, 0, 0.0, 0.0, 0, False)
    assert score.score == 0.0
    assert score.partial is True


@pytest.mark.usefixtures("_fresh_db")
async def test_empty_analysis_not_cached() -> None:
    import tempfile

    from sqlalchemy import select

    from nexus.core.database import SessionLocal
    from nexus.models.entities import Analysis, Repository
    from nexus.services.analysis import run_analysis

    empty = Path(tempfile.mkdtemp(prefix="nexus-empty-"))
    (empty / "README.md").write_text("nothing\n")
    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.commit()
        repo = (
            (await session.execute(select(Repository).where(Repository.owner == "o")))
            .scalars()
            .first()
        )
        assert repo is not None

        first = await run_analysis(session, repo, source_dir=empty)
        assert first.cache_hit is False
        assert first.analysis.status == "partial"
        assert first.analysis.health_score == 0.0

        second = await run_analysis(session, repo, source_dir=empty)
        assert second.cache_hit is False  # empty shell never masks recompute
        assert second.analysis.status == "partial"
        rows = (await session.execute(select(Analysis))).scalars().all()
        assert len(rows) == 1  # stale shell replaced, no duplicates


@pytest.mark.usefixtures("_fresh_db")
async def test_legacy_empty_cache_does_not_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scope 9 analogue: a stale v0.1.0 zero-file row must not block a fresh analysis."""
    import shutil
    import tempfile

    from sqlalchemy import select

    import nexus.services.analysis as analysis_svc
    from nexus.core.database import SessionLocal
    from nexus.github.clone import CloneResult
    from nexus.models.entities import Analysis, Repository
    from nexus.services.analysis import run_analysis

    legacy_sha = "1f59af0d92022f75f8a51fcfffc5b07e0f22d54f"

    def _fake_clone(url: str, timeout_s: int = 180) -> CloneResult:
        _ = (url, timeout_s)
        workdir = Path(tempfile.mkdtemp(prefix="nexus-legacy-"))
        shutil.copytree(FIXTURE, workdir, dirs_exist_ok=True)
        return CloneResult(workdir=workdir, sha=legacy_sha)

    monkeypatch.setattr(analysis_svc.gitclone, "clone", _fake_clone)
    async with SessionLocal() as session:
        session.add(Repository(owner="subhamxaura", name="CityRoute-Navigator", owner_user_id=None))
        await session.flush()
        repo = (
            (await session.execute(select(Repository).where(Repository.owner == "subhamxaura")))
            .scalars()
            .first()
        )
        assert repo is not None
        # The stale pre-fix row: old analyzer version, zero files, partial.
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha=legacy_sha,
                status="partial",
                health_score=100.0,
                metrics={"file_count": 0, "finding_count": 0},
                analyzer_version="v0.1.0",
            )
        )
        await session.commit()

        outcome = await run_analysis(session, repo)
        assert outcome.cache_hit is False
        assert outcome.analysis.analyzer_version != "v0.1.0"
        assert outcome.analysis.status == "complete"
        assert outcome.analysis.metrics["file_count"] == 5

        rows = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.commit_sha == legacy_sha).order_by(Analysis.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2  # legacy row untouched, fresh row added
        assert rows[0].analyzer_version == "v0.1.0"  # no unrelated data modified
