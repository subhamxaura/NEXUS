"""Request-scoped auth: JWT → User; per-repo ownership checks (404, no leakage)."""

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.database import get_session
from nexus.core.security import parse_session_token
from nexus.models.entities import Repository, User


async def get_current_user(
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    user_id = parse_session_token(authorization.removeprefix("Bearer ").strip())
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return user


async def get_owned_repo(
    repo_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Repository:
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.owner_user_id == user.id)
    )
    repo = result.scalars().first()
    if repo is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return repo
