# NEXUS Progress

## Status: Phase 3 — COMPLETE (local verification with fakes; Docker/GitHub/deploy need host + keys)
- Phase 3 decisions: Docker sandbox (network-isolated test step; lockfile-only installs in a separate networked step; read-only root, 2g/2cpu, tmpfs, 10-min cap) with truthful `unavailable` when no daemon — never a fabricated pass; Tester is deterministic (no LLM); ≤2 Coder→Tester repairs; Reviewer rejection (or score <70) blocks approval; approval is the sole GitHub-mutation path, re-checking persisted validation+review; approval-time PAT (never stored/logged, scrubbed from errors); `nexus/<id>-<slug>` branches, conventional commits, no merges; push events mark analysis stale; WS deferred to Phase 4 (2–3 s polling on the append-only log).
- Decisions carried forward: public-clone only, OpenAI primary (`llm_provider=openai`, `gpt-4o-mini`), Vercel + Railway.
- Phase 2 decisions: deterministic Orchestrator DAG (LLM reserved for Scout/Architect/Security/Coder content); schema validation lives in BaseAgent (adapters return raw JSON) so re-prompt-on-validation-error actually fires; coder diff must pass `git apply --check` with one feedback-carrying repair attempt, else `needs_human`; security `risky` verdict blocks coder (blocked task, no patch); missing LLM key → `needs_human` with reason (never a fake); API runs missions inline, arq `run_mission_job` ready for Compose.
- Windows CRLF pitfall found: text-mode temp files translate `\n`→`\r\n`, corrupting patches — `check_diff` normalizes and writes with `newline=""`. Same normalization must be used anywhere a patch touches disk (Phase 3 sandbox).
- Tree-sitter still deferred; TS heuristic unchanged.
- 2026-09-06: Empty repo inspected. Env: Win32, Python 3.13.5, Node 24.19, no Docker/Postgres/Redis locally → Compose gate must be verified in CI or Docker host; local verify via uvicorn/TestClient + SQLite + `next build`.
- Decisions: keep fixed stack; SQLite fallback for local-only (Postgres in Compose/prod); arq+Redis per spec; Fernet token encryption; radon for Python CC/MI; TS complexity = documented keyword heuristic (tree-sitter deferred); Bandit/Semgrep/audits recorded as unavailable (builtin rules in use); API runs analysis inline in Phase 1 (arq `analyze_repo_job` ready for Phase 2 orchestration); dev-only login (refuses prod/OAuth-configured); public-repo clone only (no GitHub creds per user); OpenAI adapter first in Phase 2 (user key); deploy Vercel + Railway.
- `datetime.UTC` used (py3.11+); local runs 3.13, Docker pins 3.11 — compatible.
- `next lint` (Next 14) crashes on Node 24 → lint runs `eslint .` directly. `noExplicitAny` is not a tsc option → strict stays on, `any` policed via ESLint in Phase 4.
- `ruff --fix` once ate a fixture's intentional import → `tests/fixtures` excluded from lint; B008 ignored (FastAPI Depends idiom); git-subprocess sites carry audited noqa.

## Completed slices
- (Phase 0) Monorepo scaffold, Compose (api/web/postgres/redis/worker), FastAPI health + error envelope + OpenAPI.
- (Phase 0) Next.js shell (dark, honest empty states, API-status pill, no fake data).
- (Phase 0) SQLAlchemy async + Alembic `0001_baseline` (users, repositories), `.env.example`, fail-fast env validation.
- (Phase 0) Secret-redacting logger (fixed real bug: non-string log args preserved for `%d` formatting + regression tests).
- (Phase 0) CI (backend lint/type/test, frontend lint/type/build, compose config + db/redis boot).
- (Phase 0) GitHub OAuth foundation: `GET /auth/github/login` builds authorize URL; callback validates shape, 501 until exchange — never fakes tokens.
- (Phase 1) Intelligence vertical slice: connect repo → shallow clone → deterministic pipeline → persisted analysis → dashboard + repo view (health breakdown, explorer+preview, prioritized findings, edge list + dependents). Cache key (repo, sha, analyzer_version); same-SHA rerun returns cached row.
- (Phase 2) Mission vertical slice: goal/finding → deterministic DAG (orchestrator→scout→architect→security→coder) → `git apply --check`-valid unified diff → Mission Control (plan, task timeline with I/O, live event stream, diff viewer, patch rationale) + missions tab with history. All agent I/O Pydantic-validated; tasks persist status/input/output/usage/duration/attempts/model/prompt-version; append-only event log; versioned prompts under `agents/prompts/`.
- (Phase 3) Sandbox→review→approval→PR slice: Tester (deterministic sandbox facts) → ≤2-repair loop → independent Reviewer (diff-hash-bound verdict) → explicit human approval → branch/commit/PR with audit-trail body → Mission Control shows validation runs, review, approval panel, PR link. Webhook marks stale analysis. Deploy (`docs/DEPLOY.md`) + demo (`docs/DEMO.md`) guides.

## Verification log (2026-09-06, local)
### Phase 0
- `pytest -q` → 7 passed (`apps/api`)
- `ruff check .` → All checks passed; `ruff format --check .` → clean; `mypy nexus` (strict) → clean
- Alembic `upgrade head` on SQLite → tables `alembic_version, repositories, users`
- App boot via TestClient → `GET /api/v1/health` 200 `{"status":"ok","analyzer_version":"v0.1.0"}`; OpenAPI paths: health, auth login/callback
- `npm run lint` / `typecheck` / `build` → pass (`/` 12.2 kB, First Load 99.3 kB)
- `docker-compose.yml` + `ci.yml` → YAML-valid; `docker compose up` NOT run (no Docker on this box) → must pass in CI

### Phase 1
- `pytest -q` → 19 passed (pipeline facts/edges/rules, determinism ×2, cache-hit same-ID, authz isolation, traversal guard, dev-login gate, invalid names)
- `ruff check` / `format --check` / `mypy --strict` → clean (37 files)
- Alembic `upgrade head` → + `analyses, file_metrics, dependency_edges, findings`
- Fixture analysis: 4 files, 2 edges, 8 findings, health 36.2 with reconciling breakdown
- `npm run lint` / `typecheck` / `build` → pass (`/`, `/repos/[id]` dynamic)
- NOT verified (no network/Docker here): real GitHub clone, `docker compose up`, Postgres-backed run → CI + Docker host

### Phase 2
- `pytest -q` → 32 passed (agent contracts ×5 with scripted LLM, schema-retry, transient-retry, persistent-failure, orchestrator determinism, prompt presence; mission E2E patch_ready with ordered events, security-block, diff-reject-after-repair, llm-unconfigured, ownership, cancel-gate, canned-diff-applies)
- `ruff check` / `format --check` / `mypy --strict` → clean (48 files)
- Alembic `upgrade head` → + `missions, tasks, agent_events, patches`
- `npm run lint` / `typecheck` / `build` → pass (`/missions/[id]` dynamic route added)
- NOT verified: live OpenAI/Anthropic calls (no key on this box; adapters compile under mypy, retry policy unit-covered only via fake) → needs `OPENAI_API_KEY` + Docker host

### Phase 3
- `pytest -q` → 60 passed (sandbox detection/parsing/LF-safety/unavailable, tester/reviewer agents, repair recover/exhaustion/unavailable, review-reject blocks approval, approve gates incl. mocked-GitHub happy path with branch/commit/body assertions, token scrubbing, webhook verify + stale-marking, no-PR-without-approval)
- `ruff check` / `format --check` / `mypy --strict` → clean (54 files)
- Alembic `upgrade head` → + `validation_runs, reviews, pull_requests` (14 tables)
- `npm run lint` / `typecheck` / `build` → pass (validation/review/approval/PR sections in Mission Control)
- NOT verified (needs host): real Docker validation, real GitHub PR, Compose/Postgres run, Vercel/Railway deploy → `docs/DEPLOY.md` + `docs/DEMO.md` provided

## Risks / open
- No GitHub creds → public repos only; OAuth exchange still stubbed (truthful 501).
- OpenAI key needed for Phase 2 (user confirmed); deploy Vercel + Railway in Phase 3.
- No Docker locally → sandbox (Phase 3) needs Docker host/CI for real validation.
