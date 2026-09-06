"""GitHub OAuth foundation (Phase 0): login URL + callback stub.

Real token exchange lands with DB wiring in Phase 1; this module already
builds the authorize URL and validates the callback shape truthfully
(returns 501 until exchange is implemented — never a fake token).
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query

from nexus.core.config import settings

router = APIRouter(prefix="/auth/github", tags=["auth"])


@router.get("/login")
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


@router.get("/callback")
async def callback(code: str = Query(""), state: str = Query("")) -> dict[str, str]:
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    raise HTTPException(
        status_code=501, detail="OAuth token exchange not yet implemented (Phase 1)"
    )
