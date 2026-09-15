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
from nexus.models.entities import Analysis

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


def test_scanf_comment_and_string_safety() -> None:
    """H1: comments/strings never fire the scanf rule; executable calls do."""
    code = (
        '// scanf("%s", buf);\n'  # line 1: line comment
        '/* scanf("%s", buf); */\n'  # line 2: block comment
        'char *msg = "scanf("%s", x)";\n'  # line 3: string literal
        "int f(void) {\n"
        '  scanf("%s", buf);\n'  # line 5: real unbounded -> HIT
        '  scanf("%64s", buf);\n'  # line 6: real bounded -> no hit
        '  // mixed: scanf("%s", b);\n'  # line 7: comment after real code
        '  scanf("%10s", b); scanf("%s", c);\n'  # line 8: bounded + unbounded -> ONE hit
        '  const char *hint = "use scanf("%s") carefully";\n'  # line 9: string
        "  return 0;\n"
        "}\n"
    )
    hits = parse_c(code).insecure
    assert [(h.line, h.rule_id) for h in hits] == [
        (5, "c-scanf-unbounded"),
        (8, "c-scanf-unbounded"),
    ]


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


def test_c_test_prefix_stems(tmp_path: Path) -> None:
    """L6: test_graph.c must count as the test counterpart of graph.c."""
    (tmp_path / "graph.c").write_text("int graph_add(int a, int b) { return a + b; }\n")
    (tmp_path / "test_graph.c").write_text(
        '#include "graph.h"\nint main(void) { if (graph_add(1, 2) != 3) return 1; return 0; }\n'
    )
    res = run_pipeline(tmp_path)
    files = {f.path: f for f in res.files}
    assert files["graph.c"].test_presence == 1.0
    assert not any(f.type == "missing-tests" and f.path == "graph.c" for f in res.findings)


@pytest.mark.usefixtures("_fresh_db")
@pytest.mark.parametrize("stale_status", ["pending", "running", "failed"])
async def test_stale_row_is_reused_not_duplicated(stale_status: str) -> None:
    """C1: pending/running/failed rows are reset and recomputed in place."""
    from sqlalchemy import func, select

    from nexus.core.config import settings
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Analysis, Repository
    from nexus.services.analysis import run_analysis

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha="test-sha",
                status=stale_status,
                analyzer_version=settings.analyzer_version,
                metrics={"junk": True},
            )
        )
        await session.commit()
        stale_id = (await session.execute(select(Analysis.id))).scalars().first()
        assert stale_id is not None

        outcome = await run_analysis(session, repo, source_dir=FIXTURE)

        assert outcome.cache_hit is False
        assert outcome.analysis.id == stale_id  # reused, not duplicated
        assert outcome.analysis.status == "complete"
        assert outcome.analysis.metrics["file_count"] == 5
        assert "junk" not in outcome.analysis.metrics  # previous state cleared
        total = (await session.execute(select(func.count()).select_from(Analysis))).scalar_one()
        assert total == 1


@pytest.mark.usefixtures("_fresh_db")
async def test_failed_analysis_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1: a failed analysis must not poison the SHA for later retries."""
    from sqlalchemy import func, select

    import nexus.services.analysis as analysis_svc
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Repository
    from nexus.services.analysis import run_analysis

    def _boom(workspace: object) -> object:
        raise RuntimeError("parser exploded")

    real_pipeline = analysis_svc.run_pipeline
    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        await session.commit()

        monkeypatch.setattr(analysis_svc, "run_pipeline", _boom)
        first = await run_analysis(session, repo, source_dir=FIXTURE)
        assert first.cache_hit is False
        assert first.analysis.status == "failed"
        assert "RuntimeError" in str(first.analysis.metrics.get("error", ""))

        monkeypatch.setattr(analysis_svc, "run_pipeline", real_pipeline)
        second = await run_analysis(session, repo, source_dir=FIXTURE)
        assert second.cache_hit is False
        assert second.analysis.id == first.analysis.id
        assert second.analysis.status == "complete"
        assert second.analysis.metrics["file_count"] == 5
        assert (await session.execute(select(func.count()).select_from(Analysis))).scalar_one() == 1


@pytest.mark.usefixtures("_fresh_db")
async def test_legacy_row_without_file_count_recomputes() -> None:
    """M4: a complete/partial row lacking file_count must never cache-hit."""
    from sqlalchemy import func, select

    from nexus.core.config import settings
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Analysis, Repository
    from nexus.services.analysis import run_analysis

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha="test-sha",
                status="complete",
                health_score=99.0,
                metrics={"finding_count": 3},  # no file_count: unknown, not "has files"
                analyzer_version=settings.analyzer_version,
            )
        )
        await session.commit()
        legacy_id = (await session.execute(select(Analysis.id))).scalars().first()
        assert legacy_id is not None

        outcome = await run_analysis(session, repo, source_dir=FIXTURE)

        assert outcome.cache_hit is False
        assert outcome.analysis.id == legacy_id  # recomputed in place
        assert outcome.analysis.metrics["file_count"] == 5
        assert (await session.execute(select(func.count()).select_from(Analysis))).scalar_one() == 1


@pytest.mark.usefixtures("_fresh_db")
@pytest.mark.parametrize("stale_status", ["complete", "partial"])
async def test_valid_rows_with_files_still_cache_hit(stale_status: str) -> None:
    """C1 scope guard: fresh complete/partial rows with files are untouched."""
    from sqlalchemy import func, select

    from nexus.core.config import settings
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Analysis, Repository
    from nexus.services.analysis import run_analysis

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha="test-sha",
                status=stale_status,
                health_score=42.0,
                metrics={"file_count": 5, "finding_count": 7},
                analyzer_version=settings.analyzer_version,
            )
        )
        await session.commit()
        row_id = (await session.execute(select(Analysis.id))).scalars().first()
        assert row_id is not None

        outcome = await run_analysis(session, repo, source_dir=FIXTURE)

        assert outcome.cache_hit is True
        assert outcome.analysis.id == row_id
        assert outcome.analysis.metrics["finding_count"] == 7  # not recomputed
        assert (await session.execute(select(func.count()).select_from(Analysis))).scalar_one() == 1


@pytest.mark.usefixtures("_fresh_db")
async def test_concurrent_duplicate_insert_adopts_existing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1: losing an insert race adopts the winner's row instead of crashing."""
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    import nexus.services.analysis as analysis_svc
    from nexus.core.config import settings
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Repository
    from nexus.services.analysis import run_analysis

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha="test-sha",
                status="pending",
                analyzer_version=settings.analyzer_version,
            )
        )
        await session.commit()

        real_lookup = analysis_svc._locked_row_for_key
        calls = {"n": 0}

        async def _hide_first(session: AsyncSession, repo_id: int, sha: str) -> Analysis | None:
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # simulate a rival creating the row after our check
            return await real_lookup(session, repo_id, sha)

        monkeypatch.setattr(analysis_svc, "_locked_row_for_key", _hide_first)
        outcome = await run_analysis(session, repo, source_dir=FIXTURE)

        assert calls["n"] >= 2  # insert raced, rolled back, adopted
        assert outcome.cache_hit is False
        assert outcome.analysis.status == "complete"
        assert outcome.analysis.metrics["file_count"] == 5
        assert (await session.execute(select(func.count()).select_from(Analysis))).scalar_one() == 1


@pytest.mark.usefixtures("_fresh_db")
async def test_concurrent_fresh_row_wins_returns_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1: if the rival already finished a fresh analysis, serve it as a hit."""
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    import nexus.services.analysis as analysis_svc
    from nexus.core.config import settings
    from nexus.core.database import SessionLocal
    from nexus.models.entities import Repository
    from nexus.services.analysis import run_analysis

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo is not None
        session.add(
            Analysis(
                repo_id=repo.id,
                commit_sha="test-sha",
                status="complete",
                health_score=77.0,
                metrics={"file_count": 5, "finding_count": 14},
                analyzer_version=settings.analyzer_version,
            )
        )
        await session.commit()
        row_id = (await session.execute(select(Analysis.id))).scalars().first()
        assert row_id is not None

        real_lookup = analysis_svc._locked_row_for_key
        calls = {"n": 0}

        async def _hide_first(session: AsyncSession, repo_id: int, sha: str) -> Analysis | None:
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_lookup(session, repo_id, sha)

        monkeypatch.setattr(analysis_svc, "_locked_row_for_key", _hide_first)
        outcome = await run_analysis(session, repo, source_dir=FIXTURE)

        assert outcome.cache_hit is True
        assert outcome.analysis.id == row_id
        assert (await session.execute(select(func.count()).select_from(Analysis))).scalar_one() == 1


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
