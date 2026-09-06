# NEXUS — AI Software-Engineering Command Center

Golden path: GitHub repo → analyze → findings → mission → plan → patch → sandbox → review → human approval → PR.

Deterministic systems own analysis, scoring, gates, and guardrails. LLMs handle bounded reasoning (planning, patches, review) with schema-validated outputs. No code reaches GitHub without real validation and explicit human approval.

## Quickstart (Docker)
```bash
cp .env.example .env   # fill JWT_SECRET + TOKEN_FERNET_KEY at minimum
docker compose up --build
# web http://localhost:3000 · api http://localhost:8000/health · docs http://localhost:8000/docs
docker compose exec api alembic upgrade head
```

## Local (no Docker, dev-box fallback)
```bash
cd apps/api && pip install -r requirements.txt -r requirements-dev.txt
set DATABASE_URL=sqlite+aiosqlite:///./nexus_dev.db && python -m pytest -q
python -m uvicorn nexus.main:app --port 8000
cd ../web && npm install && npm run dev
```

## Checks
```bash
# backend (apps/api)
ruff check . && ruff format --check . && mypy nexus
pytest -q --cov --cov-report=term --cov-fail-under=80
PYTHONPATH=. python scripts/gen_types.py  # regenerates packages/shared-types
# frontend (apps/web)
npm run lint && npm run typecheck && npm run build
```

Coverage target: ≥80% total, ≥80% on every safety-critical module
(`intelligence/`, `agents/`, `github/`, `sandbox/`, mission transitions).
Exceptions are host-only by nature and documented in `docs/PROGRESS.md`:
live-LLM adapters (need a key), Docker execution paths (need a daemon).

## Environment
All variables are documented in `.env.example`. The essentials:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` / `REDIS_URL` | Postgres + Redis (SQLite fallback for local dev only) |
| `JWT_SECRET` / `TOKEN_FERNET_KEY` | Sessions + encrypted GitHub tokens |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `LLM_PROVIDER` | Mission agents (no key → honest `needs_human`, never faked) |
| `GITHUB_CLIENT_ID/SECRET`, `GITHUB_WEBHOOK_SECRET` | OAuth identity + verified webhooks |
| `ENVIRONMENT=production` | Disables the dev-only login |

## Docs
- `docs/ARCHITECTURE.md` — components, flows, data model, scoring formulas
- `docs/IMPLEMENTATION_PLAN.md` — phased build plan and gates
- `docs/SECURITY.md` — security model + self-review
- `docs/LIMITATIONS.md` — honest MVP boundaries
- `docs/DEPLOY.md` — Vercel + Railway deployment
- `docs/DEMO.md` — 10-minute safe demo script
- `docs/PROGRESS.md` — build log with verification evidence

## Safety
No default-branch writes, no auto-merge, approval-gated PRs, network-isolated sandbox, secret redaction. See `docs/SECURITY.md`.
