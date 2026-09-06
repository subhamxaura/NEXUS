# NEXUS Known Limitations (MVP)

Honest boundaries, verified where stated. Anything not listed here but
unimplemented is a bug, not a limitation — please report it.

## Languages
- **Python and TypeScript/JavaScript only.** Go/Java files are detected and
  labeled "planned" but not analyzed. Other languages are ignored silently in
  file counts (only supported files count toward `file_count`).
- TS/JS complexity is a **keyword heuristic** (`complexity_source:
  "heuristic-ts-v1"`), not control-flow analysis. Treat it as a smell, not a grade.

## Analysis
- Max **2000 supported files** and **1 MB per file**; excess is listed in
  `metrics.skipped` and forces `status: partial`.
- Churn reflects the **shallow clone depth (50 commits)**, not full history.
- Test-presence is a **filename heuristic** (`test_*`, `*.test.*`,
  `tests/` dirs), not import tracing — it over-credits conventional layouts
  and under-credits unusual ones.
- Entropy secret scan has **known false positives** (long URLs, fixtures);
  regex/backslash/space guards reduce but don't eliminate them. No finding
  alone proves a leak — investigate before rotating.
- Optional analyzers (Bandit, Semgrep, dependency audits) are **not wired**;
  availability is reported per analysis. Builtin pattern rules cover the
  common insecure-call cases only.

## Missions & agents
- Live missions require an **LLM provider key**; without one they end as
  `needs_human` (never faked).
- Context is **bounded** (top-30 risky files, 6 files × 12 KB chars for
  proposals). Large-repo missions may miss relevant code — narrow the goal
  or start from a specific finding.
- Agent outputs are **probabilistic**: schemas, retries, gates, and human
  approval bound the risk, but review every diff yourself.

## Validation & PRs
- Sandbox validation requires a **Docker daemon** reachable from the
  API/worker host; otherwise `unavailable` → `needs_human`.
- Offline test execution means repositories needing **unlisted system
  dependencies** (databases, browsers, private registries) will fail
  validation truthfully rather than pass weakly.
- PR creation needs a **token with contents:write + pull_requests:write**
  at approval time. NEXUS never merges; default-branch writes are refused
  in code, not just policy.

## Realtime & scale
- No WebSocket streaming yet — the UI **polls** `/events` every 2–3 s.
  The append-only event log is the replayable source of truth.
- Single-worker execution; concurrent missions queue behind arq/Redis.
- No cost dashboard yet; token usage is recorded per task and visible in
  Mission Control.

## Demo artifacts
- No screenshots/GIFs are bundled; capture them from a live deployment
  following `docs/DEMO.md`.
