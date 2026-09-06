# NEXUS — AI Software-Engineering Command Center

Golden path: GitHub repo → analyze → findings → mission → plan → patch → sandbox → review → human approval → PR.

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

## Docs
- `docs/ARCHITECTURE.md` · `docs/IMPLEMENTATION_PLAN.md` · `docs/SECURITY.md` · `docs/PROGRESS.md`

## Safety
No default-branch writes, no auto-merge, approval-gated PRs, network-isolated sandbox, secret redaction. See `docs/SECURITY.md`.
