# NEXUS Implementation Plan (2–3 week MVP)

Golden-path escalation rule: if work doesn't raise P(golden path completes), defer it.

## Phase 0 — Foundation (current)
- [x] Monorepo scaffold, Compose (api/web/postgres/redis/worker)
- [x] FastAPI health + error envelope + OpenAPI
- [x] Next.js shell (dark, empty states)
- [x] SQLAlchemy async + Alembic baseline, `.env.example`, env validation
- [x] Structured logging w/ secret redaction
- [x] CI (lint/type/test/build), GitHub OAuth foundation
- Gate: `docker compose up` → login-capable app, health check, migrated DB, empty dashboard.
- Local note: this dev box has no Docker/Postgres/Redis; verify via `uvicorn`+SQLite fallback + `next build`/`pytest`.

## Phase 1 — Repository Intelligence
Files: `intelligence/{detector,python_parser,ts_parser,graph,metrics,churn,secrets_scanner,scoring,findings,pipeline}.py`, `services/analysis.py`, `workers/analyze.py`, `api/v1/{repos,analysis}.py`, web repo view.
Findings: complexity hotspot, missing tests, secret hit, risky dependency, God-file.
Gate: real public repo analyzed, persisted, visible; same-SHA rerun hits cache.

## Phase 2 — Mission Planning + Patch
Files: `llm/{client,anthropic,openai,retry,usage}.py`, `agents/{base,orchestrator,scout,architect,security,coder,tester,reviewer,prompts/*}.py`, `services/missions.py`, mission-control UI.
Gate: mission → traceable plan + real unified diff. No GitHub mutation.

## Phase 3 — Sandbox, Review, Approval, PR
Files: `sandbox/{runner,docker,parser}.py`, `github/{client,branches,prs,webhooks}.py`, approval endpoint+UI, webhook sync, prod deploy, demo script.
Repair loop ≤2. Reviewer rejection blocks PR. Approval required.
Gate: safe test repo → real E2E PR after human approval.

## Phase 4 — Polish/Hardening
Graph UX, finding explanations, error recovery, a11y, limitations doc, security review, demo GIF, prod verification.

## Test strategy
80%+ on `intelligence/agents/github/sandbox/state-transitions`; mocked-LLM agent tests; integration: authz, cache-hit, bad-diff reject, sandbox fail→needs_human, review-reject blocks PR, approve-gate.
