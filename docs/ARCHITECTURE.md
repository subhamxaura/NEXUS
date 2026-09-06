# NEXUS Architecture

## 1. Overview
NEXUS is an AI-assisted software engineering command center. Golden path:

```
GitHub repo → analyze → findings → mission → plan → patch → sandbox → review → approval → PR
```

Deterministic systems own analysis, scoring, scheduling, caching, guardrails.
LLMs own bounded reasoning: planning, patch generation, explanation, review, repair guidance.
Every AI output is Pydantic-validated; every consequential action is observable, replayable, gated.

## 2. Components

```
apps/web (Next.js 14, TS, Tailwind, TanStack Query, Zustand)
  ↕ REST /api/v1 + WS /ws/*
apps/api (FastAPI, Pydantic v2, SQLAlchemy 2.0 async, Alembic, arq)
  ├── api/v1        routers, auth deps, error envelope
  ├── intelligence  parsers (ast/tree-sitter), graphs (NetworkX), metrics, findings, scoring
  ├── agents        BaseAgent + Orchestrator/Scout/Architect/Security/Coder/Tester/Reviewer
  ├── llm           provider-agnostic LLMClient (Anthropic default, OpenAI adapter), retry, accounting
  ├── github        OAuth/App auth, clone, branch/commit/PR, webhooks (HMAC verify)
  ├── sandbox       Docker runner (--network none, 2g/2cpu, read-only, tmpfs, 10min)
  ├── services      business logic + mission state machine (sole transition authority)
  ├── models        SQLAlchemy models (see §4)
  ├── realtime      Redis pub/sub + WS manager, append-only AgentEvent log
  ├── workers       arq jobs (analyze, mission DAG)
  └── core          config, db, redis, logging (secret redaction), security
Postgres 15+ (persistent) · Redis 7 (queue/cache/pubsub/locks)
```

## 3. Request flows
- **Analyze:** `POST /repos/{id}/analyze` → shallow clone (`--depth 50`, isolated workspace) → intelligence pipeline → persist `Analysis`+children → cache key `(repo_id, sha, analyzer_version)` (same-SHA rerun returns the cached row).
- **Mission:** `POST /repos/{id}/missions` → deterministic DAG (Scout→Architect→Security→Coder→Tester→Reviewer) → `needs_human` or `awaiting_approval` → `POST /missions/{id}/approve` (human only, GitHub token) → branch/commit/PR.
- **Events:** services emit `started|progress|completed|failed|retrying|blocked` → persisted append-only `AgentEvent` rows, polled by the UI every 2–3 s. Redis pub/sub + WebSocket streaming is deferred to Phase 4; the persisted log is already the replayable source of truth.

## 4. Data model (Alembic-managed)
User, Repository, Analysis (uniq repo+sha), FileMetric, DependencyEdge, Finding,
Mission, Task, AgentEvent (append-only), Patch, ValidationRun, Review, PullRequest.
State transitions enforced only in `services/missions.py`.

## 5. Determinism vs LLM boundary
Deterministic: parsing, graphs, complexity, LOC/MI, churn, risk/health scoring, prioritization, cache, DAG execution, state transitions.
LLM (schema-bound, budgeted, max 3 retries w/ backoff, repair loop ≤2): planning, diff generation, explanation, review, repair guidance.

## 6. Risk & health scoring
```
file_risk = w1*norm_complex + w2*norm_churn + w3*norm_central + w4*sec_signal + w5*(1-test_proxy)
priority  = severity × confidence × file_risk × reachability
health    = 0–100 with visible breakdown (complexity, security, testing, structure, freshness)
```
Weights in config; every score exposes contributors. No unexplained "AI risk".

## 7. Sandbox
Copy immutable snapshot → `git apply --check` → apply → install from lockfile only → run detected test command → lint/build if reliable → collect exit/duration/logs → `ValidationReport`. Never host-exec, never mount secrets.

## 8. Security summary
GitHub App (least privilege) + OAuth identity; Fernet-encrypted tokens; webhook HMAC; no default-branch writes; no auto-merge; approval-gated mutation; secret redaction in logs/events/LLM ctx; authz check per repo/mission endpoint. Details: `docs/SECURITY.md`.

## 9. Deploy
Web → Vercel; API/worker/Postgres/Redis → Railway/Fly.io; local → Docker Compose. OpenAPI → `packages/shared-types`.
