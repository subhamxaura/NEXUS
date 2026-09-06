# NEXUS Progress

## Status: Phase 0 — COMPLETE (local verification; Compose gate needs Docker host/CI)
- 2026-09-06: Empty repo inspected. Env: Win32, Python 3.13.5, Node 24.19, no Docker/Postgres/Redis locally → Compose gate must be verified in CI or Docker host; local verify via uvicorn/TestClient + SQLite + `next build`.
- Decisions: keep fixed stack; SQLite fallback for local-only (Postgres in Compose/prod); arq+Redis per spec; Fernet token encryption; NetworkX intelligence in Phase 1.
- `datetime.UTC` used (py3.11+); local runs 3.13, Docker pins 3.11 — compatible.
- `next lint` (Next 14) crashes on Node 24 → lint runs `eslint .` directly. `noExplicitAny` is not a tsc option → strict stays on, `any` policed via ESLint in Phase 4.

## Completed slices
- Monorepo scaffold, Compose (api/web/postgres/redis/worker), FastAPI health + error envelope + OpenAPI.
- Next.js shell (dark, honest empty states, API-status pill, no fake data).
- SQLAlchemy async + Alembic `0001_baseline` (users, repositories), `.env.example`, fail-fast env validation.
- Secret-redacting logger (fixed real bug: non-string log args preserved for `%d` formatting + regression tests).
- CI (backend lint/type/test, frontend lint/type/build, compose config + db/redis boot).
- GitHub OAuth foundation: `GET /auth/github/login` builds authorize URL; callback validates shape, 501 until Phase 1 exchange — never fakes tokens.

## Verification log (2026-09-06, local)
- `pytest -q` → 7 passed (`apps/api`)
- `ruff check .` → All checks passed; `ruff format --check .` → clean; `mypy nexus` (strict) → clean
- Alembic `upgrade head` on SQLite → tables `alembic_version, repositories, users`
- App boot via TestClient → `GET /api/v1/health` 200 `{"status":"ok","analyzer_version":"v0.1.0"}`; OpenAPI paths: health, auth login/callback
- `npm run lint` / `typecheck` / `build` → pass (`/` 12.2 kB, First Load 99.3 kB)
- `docker-compose.yml` + `ci.yml` → YAML-valid; `docker compose up` NOT run (no Docker on this box) → must pass in CI

## Risks / open (material decisions for user)
- Need GitHub OAuth App creds (client id/secret) + App private key + webhook secret for Phase 1/3.
- Need LLM provider key (Anthropic default) for Phase 2.
- Need deploy targets confirmation: Vercel (web) + Railway/Fly.io (api/worker/db) per spec?
- No Docker locally → sandbox (Phase 3) needs Docker host/CI for real validation.
