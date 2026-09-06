"""GitHub OAuth foundation + development-only local login.

`POST /auth/dev-login` exists ONLY for local development without GitHub
credentials (Phase 1): it refuses to run in production or when OAuth is
configured, so it can never become a backdoor.
"""

import secrets
import zlib
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.config import settings
from nexus.core.database import get_session
from nexus.core.security import create_session_token
from nexus.models.entities import User

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginIn(BaseModel):
    login: str = Field(default="developer", min_length=1, max_length=39, pattern=r"^[A-Za-z0-9-]+$")


@router.post("/dev-login")
async def dev_login(
    body: DevLoginIn, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    if settings.environment != "development" or settings.github_client_id:
        raise HTTPException(status_code=403, detail="dev login is disabled")
    github_id = -abs(zlib.crc32(body.login.encode())) - 1
    result = await session.execute(select(User).where(User.github_id == github_id))
    user = result.scalars().first()
    if user is None:
        user = User(github_id=github_id, login=body.login, encrypted_token="")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return {"token": create_session_token(user.id), "login": user.login}


github_router = APIRouter(prefix="/auth/github", tags=["auth"])


@github_router.get("/login")
async def login() -> dict[str, str]:
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    state = secrets.token_urlsafe(16)
    q = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": "http://localhost:3000/api/auth/callback",
            "scope": "read:user repo",
            "state": state,
        }
    )
    return {"authorize_url": f"https://github.com/login/oauth/authorize?{q}", "state": state}


@github_router.get("/callback")
async def callback(code: str = Query(""), state: str = Query("")) -> dict[str, str]:
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    raise HTTPException(
        status_code=501, detail="OAuth token exchange not yet implemented (Phase 1)"
    )
