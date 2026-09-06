"""Consistent error envelope + health + versioned router."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthOut(BaseModel):
    status: str
    analyzer_version: str
    environment: str


class ErrorOut(BaseModel):
    error: str
    detail: str = ""
    code: str = "bad_request"


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    from nexus.core.config import settings

    return HealthOut(
        status="ok", analyzer_version=settings.analyzer_version, environment=settings.environment
    )
