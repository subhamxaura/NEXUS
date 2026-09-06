# NEXUS Security Model

## Self-review (2026-09-06, Phase 4)
Dogfooded the NEXUS scanner on this repository (86 files): **zero real
secrets** — no AWS keys, GitHub tokens, private keys, or hardcoded passwords.
Two expected scanner hits are test fixtures by design (`AKIAIOSFODNN7EXAMPLE`
assertion, `test-token-abc` approval fake). No `.env` is tracked; token-shaped
test values use non-secret-looking strings.
Also verified: authz isolation tests, approve-gate tests (wrong state, double
approve, foreign user), token scrubbing in git errors, webhook HMAC tests,
secret-redaction unit tests. See `docs/PROGRESS.md` verification logs.

## Principles
Least privilege · explicit approval · isolation · redaction · auditability.

## Rules (non-negotiable)
1. Never push to default branch; never auto-merge. Mutation path only: isolated branch `nexus/<mission-id>-<slug>` → commit (`Co-authored-by: NEXUS <bot@nexus>`) → PR.
2. `POST /missions/{id}/approve` (human JWT, repo owner) is the sole gate to branch/commit/PR. Reviewer approval ≠ human approval.
3. Repo code runs ONLY in Docker sandbox: `--network none --memory 2g --cpus 2 --read-only`, tmpfs workspace, 10-min timeout, pinned `python:3.11-slim`/`node:20-slim`. No host exec, no secret mounts, lockfile-only installs.
4. Never log tokens/keys/headers/secrets/env. `core/logging.py` redacts `(?i)(github_token|api[_-]?key|authorization|bearer|secret|passwd|private_key)` + `ghp_|gho_|github_pat_` patterns; applied to logs, events, errors, LLM context.
5. GitHub webhooks verified via HMAC-SHA256 (`X-Hub-Signature-256`); reject on mismatch; `push` marks analysis stale.
6. Tokens encrypted at rest (Fernet; KMS-backed in prod); min-scope GitHub App (`contents:rw`, `pull_requests:write`, `metadata:read`); every repo/mission endpoint checks ownership; no cross-user leakage.
7. Shallow clone `--depth 50` into unique per-mission workspace; never reuse across repos/missions. Private repos rejected unless explicitly authorized.
8. `git apply --check` before apply; invalid diffs rejected pre-sandbox.
9. Budgets per task (time/tokens); retries ≤3 exp-backoff; schema-fail → re-prompt with validation error; Coder→Tester→Reviewer repairs ≤2; else `needs_human` with full trace. Fail visible, never silent skip.
10. PR body is factual: goal, finding, diff summary, impact, real validation + review verdicts, limitations, trace link. No claimed checks.

## Coverage
Secret-redaction unit tests, authz tests, approve-gate tests, webhook-signature tests required in CI.
