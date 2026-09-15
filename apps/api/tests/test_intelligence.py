import subprocess
from pathlib import Path

from nexus.intelligence.churn import batch_churn, file_churn
from nexus.intelligence.metrics import python_numbers, ts_numbers
from nexus.intelligence.pipeline import run_pipeline
from nexus.intelligence.python_parser import parse_python
from nexus.intelligence.scoring import file_risk

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_pipeline_finds_expected_facts() -> None:
    res = run_pipeline(FIXTURE)
    assert res.file_count == 4
    assert {f.path for f in res.files} == {"risky.py", "helpers.py", "app.ts", "lib.ts"}
    assert ("helpers.py", "risky.py", "import") in res.edges
    assert ("app.ts", "lib.ts", "import") in res.edges
    rule_ids = {f.rule_id for f in res.findings}
    assert "py-eval-exec" in rule_ids
    assert "py-pickle" in rule_ids
    assert "py-subprocess-shell" in rule_ids
    assert "secret-aws-access-key" in rule_ids
    assert "missing-tests" in rule_ids
    # Highest-risk file first when sorted by risk.
    by_risk = sorted(res.files, key=lambda f: -f.risk)
    assert by_risk[0].path == "risky.py"
    # Risk contributors are explainable.
    assert set(by_risk[0].risk_contributors) == {
        "complexity",
        "churn",
        "centrality",
        "security",
        "untested",
    }
    # Health breakdown reconciles with the score.
    assert abs(100.0 - sum(res.health_breakdown.values()) - res.health) < 0.1


def test_pipeline_deterministic() -> None:
    assert run_pipeline(FIXTURE) == run_pipeline(FIXTURE)


def test_python_parse_error_honest() -> None:
    facts = parse_python("def broken(:\n")
    assert facts.parse_error is not None
    assert facts.imports == ()


def test_ts_complexity_source_labeled() -> None:
    nums = ts_numbers("if (a) { for (;;) {} }")
    assert nums.complexity_source == "heuristic-ts-v1"
    assert nums.maintainability is None
    py = python_numbers("x = 1\n")
    assert py.complexity_source == "radon"


def test_churn_zero_without_history(tmp_path: Path) -> None:
    assert batch_churn(tmp_path, ["nope.py"]) == {"nope.py": 0}


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603 -- fixed git binary, test fixture only
        ["git", *args],  # noqa: S607 -- fixed git binary, test fixture only
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_batch_churn_matches_per_file_on_real_history(tmp_path: Path) -> None:
    """Batched churn must equal the per-file reference on the same history."""
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 1\n")
    (tmp_path / "c.py").write_text("z = 1\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "c1", cwd=tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "c2", cwd=tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n")
    (tmp_path / "b.py").write_text("y = 3\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "c3", cwd=tmp_path)

    paths = ["a.py", "b.py", "c.py"]
    expected = {p: file_churn(tmp_path, p) for p in paths}
    assert expected == {"a.py": 2, "b.py": 2, "c.py": 1}
    assert batch_churn(tmp_path, paths) == expected

    # Batching edge: more than one _BATCH_SIZE batch stays equivalent.
    assert batch_churn(tmp_path, paths * 250) == {p: expected[p] for _ in range(250) for p in paths}


def test_batch_churn_skips_merge_and_rename_noise(tmp_path: Path) -> None:
    """Renames must not credit the old path (pre-fix semantics preserved)."""
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "old.py").write_text("x = 1\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "c1", cwd=tmp_path)
    (tmp_path / "old.py").rename(tmp_path / "new.py")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "c2", cwd=tmp_path)

    counts = batch_churn(tmp_path, ["old.py", "new.py"])
    # Exactly the per-file reference (pre-fix --no-renames semantics: the
    # delete of old.py counts, the rename is never credited as a copy).
    assert counts == {p: file_churn(tmp_path, p) for p in ("old.py", "new.py")}
    assert counts["new.py"] == 1
    assert counts["old.py"] == 2


def test_file_risk_bounded() -> None:
    breakdown = file_risk(999.0, 999, 5.0, 3.0, -2.0)
    assert 0.0 <= breakdown.risk <= 1.0
    assert set(breakdown.contributors) == {
        "complexity",
        "churn",
        "centrality",
        "security",
        "untested",
    }


def test_entropy_skips_regex_and_paths() -> None:
    from nexus.intelligence.secrets_scanner import scan_text

    assert scan_text(r'x = re.compile(r"(?i)(abc|def)[0-9]{16}")') == ()
    assert scan_text('p = "C:\\Users\\someverylongdirectoryname\\file.txt"') == ()
    assert scan_text('key = "AKIAIOSFODNN7EXAMPLE"') != ()


def test_test_files_exempt_from_size_rules(tmp_path: Path) -> None:
    big_test = tmp_path / "test_big.py"
    big_test.write_text(
        "import x\n" + "\n".join(f"def test_{i}(): assert True" for i in range(300))
    )
    res = run_pipeline(tmp_path)
    assert res.file_count == 1
    assert all(f.type not in ("high-complexity", "god-file") for f in res.findings)


def test_nested_test_dirs_detected(tmp_path: Path) -> None:
    from nexus.intelligence.pipeline import _is_test_path

    assert _is_test_path("tests/testserver/server.py")
    assert _is_test_path("test/helpers.py")
    assert not _is_test_path("src/contest.py")
