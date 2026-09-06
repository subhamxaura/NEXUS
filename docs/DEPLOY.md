# NEXUS Deployment (Vercel + Railway)

## Web → Vercel
1. Import `apps/web` as the project root (or the monorepo with root directory `apps/web`).
2. Environment: `NEXT_PUBLIC_API_BASE_URL=https://<api-domain>`.
3. Build: `npm run build`. No `vercel.json` needed (Next.js auto-detected).

## API + worker + Postgres + Redis → Railway
1. Create a Railway project from this repo; add Postgres 15+ and Redis 7 plugins.
2. API service: root directory `apps/api`, builder Dockerfile. Start: `uvicorn nexus.main:app --host 0.0.0.0 --port $PORT`.
3. Worker service: same image/Dockerfile, start: `arq nexus.workers.settings.WorkerSettings`.
4. Required env (see `.env.example`): `DATABASE_URL` (asyncpg), `REDIS_URL`,
   `JWT_SECRET` (≥32 chars), `TOKEN_FERNET_KEY`, `ENVIRONMENT=production`,
   `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`, GitHub OAuth/App vars,
   `GITHUB_WEBHOOK_SECRET`, `SANDBOX_*`.
5. Run `alembic upgrade head` on deploy (Railway pre-deploy command).
6. The API container needs `git` (installed in Dockerfile) and access to a
   Docker daemon for sandbox validation — run the worker/API on a host with
   Docker available (Railway private networking + Docker-in-Docker sidecar, or
   Fly.io with a Docker host). Without a daemon, validation truthfully reports
   `unavailable` and missions end as `needs_human` — nothing is faked.

## GitHub App / webhooks
- Register the webhook URL `https://<api-domain>/webhooks/github` with
  `X-Hub-Signature-256` verification (`GITHUB_WEBHOOK_SECRET`).
- Prefer a GitHub App (least privilege: `contents:read/write`,
  `pull_requests:write`, `metadata:read`); a fine-grained PAT works for trials
  and is supplied at approval time (never stored server-side).

## Checklist before going live
- [ ] `ENVIRONMENT=production` (disables dev-login)
- [ ] Real `JWT_SECRET`, `TOKEN_FERNET_KEY`, webhook secret
- [ ] Alembic at head; Postgres/Redis reachable; Docker daemon reachable
- [ ] Golden-path smoke test on a safe repository (see `docs/DEMO.md`)
