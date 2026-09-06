# Contributing to NEXUS

Phase-0 rules (enforced in CI):
- Backend: `ruff check .`, `ruff format --check .`, `mypy nexus` (strict), `pytest -q`.
- Frontend: `npm run lint`, `npm run typecheck`, `npm run build`.
- Every schema change ships an Alembic migration.
- Never commit secrets, tokens, or `.env`. Copy `.env.example` to `.env` locally.
- Keep slices vertical and small; update `docs/PROGRESS.md` with verification commands + results.
