# NEXUS Demo Script (safe end-to-end, ~10 minutes)

Use a small public repository you own (or a scratch fork). Never demo on a
repository you cannot afford to receive a pull request on.

## 0. Setup
```bash
cp .env.example .env   # set JWT_SECRET, OPENAI_API_KEY
docker compose up --build
# web http://localhost:3000 · api http://localhost:8000/docs
docker compose exec api alembic upgrade head
```

## 1. Connect (1 min)
Dashboard → "Connect a public repository" → owner + name → Connect.

## 2. Analyze (1–3 min)
Click Analyze. Re-clicking at the same SHA returns the cached row
(`cache_hit: true` in the API response).

Show: health score + penalty breakdown, analyzer availability list,
risk-ranked explorer (hover a risk score for contributors), prioritized
findings, import edges + dependents.

## 3. Mission (3–6 min, needs `OPENAI_API_KEY`)
Repo → Missions → goal "Fix the highest-risk issue." → pick the top finding →
Start mission → open Mission Control.

Narrate: deterministic plan → Scout → Architect → Security gate → Coder diff
(`git apply --check`-valid) → Docker sandbox validation (real logs) →
independent Reviewer verdict.

## 4. Approval → PR (1 min, needs a GitHub token)
Only when status is `awaiting_approval`: paste a fine-grained PAT
(contents:write, pull_requests:write) → Approve & open pull request.

Show: branch `nexus/<id>-<slug>`, conventional commit with
`Co-authored-by: NEXUS <bot@nexus>`, PR body with goal / finding / validation /
review / trace. Emphasize: no merge happens — a human merges on GitHub.

## 5. Failure paths (optional, 2 min)
- Remove `OPENAI_API_KEY` → mission ends `needs_human` (reason shown).
- Stop Docker → validation `unavailable` → `needs_human`, nothing fabricated.
- Reviewer rejection (try a risky goal) → approval button never appears.

## Talking points
Deterministic analysis/scores/gates; LLMs only for bounded reasoning; every AI
output schema-validated; every mutation approval-gated; full audit trace.
