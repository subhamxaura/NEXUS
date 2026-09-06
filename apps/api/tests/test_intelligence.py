from pathlib import Path

from nexus.intelligence.churn import batch_churn
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
