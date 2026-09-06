"""GitHub webhook handling: signature-verified, minimal, honest.

- `push` to the tracked default branch marks the stored analysis stale by
  clearing `last_analyzed_sha` (the next dashboard visit shows "never
  analyzed" rather than silently outdated results).
- `pull_request` events are acknowledged and logged; NEXUS never merges.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.entities import Repository


async def handle_push(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    repo_payload = payload.get("repository") or {}
    full_name = str(repo_payload.get("full_name") or "")
    if "/" not in full_name:
        return {"status": "ignored"}
    owner, name = full_name.split("/", 1)
    result = await session.execute(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    repo = result.scalars().first()
    if repo is None:
        return {"status": "unknown-repo"}
    ref = str(payload.get("ref") or "")
    if ref == f"refs/heads/{repo.default_branch}":
        repo.last_analyzed_sha = None
        await session.commit()
        return {"status": "marked-stale", "repo": full_name}
    return {"status": "ignored-ref", "repo": full_name}
