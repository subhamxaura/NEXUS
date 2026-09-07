"""Risk, priority, and health scoring. All formulas documented and explainable.

file_risk = w1*norm_complex + w2*norm_churn + w3*norm_central
          + w4*sec_signal + w5*(1 - test_proxy)

priority  = severity_w * confidence * file_risk * reachability
health    = 0-100 with category breakdown; every score exposes contributors.
"""

from dataclasses import dataclass

DEFAULT_WEIGHTS: dict[str, float] = {
    "complexity": 0.25,
    "churn": 0.15,
    "centrality": 0.20,
    "security": 0.25,
    "untested": 0.15,
}

SEVERITY_WEIGHT: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "low": 0.25,
    "info": 0.1,
}

# Normalization ceilings (documented, configurable).
COMPLEXITY_CEIL = 30.0
CHURN_CEIL = 20.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(frozen=True)
class RiskBreakdown:
    risk: float
    contributors: dict[str, float]


def file_risk(
    complexity: float,
    churn: int,
    centrality: float,
    security_signal: float,
    test_proxy: float,
    weights: dict[str, float] | None = None,
) -> RiskBreakdown:
    w = weights or DEFAULT_WEIGHTS
    parts = {
        "complexity": _clamp01(complexity / COMPLEXITY_CEIL),
        "churn": _clamp01(churn / CHURN_CEIL),
        "centrality": _clamp01(centrality),
        "security": _clamp01(security_signal),
        "untested": 1.0 - _clamp01(test_proxy),
    }
    risk = round(
        w["complexity"] * parts["complexity"]
        + w["churn"] * parts["churn"]
        + w["centrality"] * parts["centrality"]
        + w["security"] * parts["security"]
        + w["untested"] * parts["untested"],
        4,
    )
    return RiskBreakdown(risk=risk, contributors={k: round(v, 4) for k, v in parts.items()})


def finding_priority(
    severity: str,
    confidence: float,
    risk: float,
    reachability: float,
) -> float:
    return round(
        SEVERITY_WEIGHT.get(severity, 0.1)
        * _clamp01(confidence)
        * _clamp01(risk)
        * _clamp01(reachability),
        4,
    )


@dataclass(frozen=True)
class HealthScore:
    score: float
    breakdown: dict[str, float]
    partial: bool


def health_score(
    avg_complexity: float,
    security_count: int,
    untested_ratio: float,
    hotspot_ratio: float,
    file_count: int,
    partial: bool,
) -> HealthScore:
    """Penalty-based 0-100 score.

    Zero analyzed files is not a healthy project: score 0 with an explicit
    penalty contributor instead of a misleading 100.
    """
    if file_count == 0:
        return HealthScore(score=0.0, breakdown={"no_supported_files": 100.0}, partial=True)
    complexity_pen = min(30.0, avg_complexity * 2.0)
    security_pen = min(35.0, security_count * 7.0)
    testing_pen = round(20.0 * _clamp01(untested_ratio), 2)
    structure_pen = round(15.0 * _clamp01(hotspot_ratio), 2)
    breakdown = {
        "complexity": round(complexity_pen, 2),
        "security": round(security_pen, 2),
        "testing": testing_pen,
        "structure": structure_pen,
    }
    return HealthScore(
        score=round(max(0.0, 100.0 - sum(breakdown.values())), 1),
        breakdown=breakdown,
        partial=partial,
    )
