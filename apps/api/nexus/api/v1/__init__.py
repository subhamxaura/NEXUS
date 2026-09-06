from fastapi import APIRouter

from nexus.api.v1.auth import router as auth_router
from nexus.api.v1.routes import router as core_router

v1 = APIRouter(prefix="/api/v1")
v1.include_router(core_router, tags=["core"])
v1.include_router(auth_router)
