# NEXUS Progress

## Status: Phase 1 — COMPLETE (local verification; real-GitHub + Compose gates need network/Docker host)
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

## Risks / open
- No GitHub creds → public repos only; OAuth exchange still stubbed (truthful 501).
- OpenAI key needed for Phase 2 (user confirmed); deploy Vercel + Railway in Phase 3.
- No Docker locally → sandbox (Phase 3) needs Docker host/CI for real validation.
