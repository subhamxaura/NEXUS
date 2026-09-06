"""FastAPI app with error envelope + redacting logger."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nexus.api.v1 import v1
from nexus.api.webhooks import router as webhook_router
from nexus.core.logging import configure_logging

log = configure_logging()
app = FastAPI(title="NEXUS API", version="0.1.0")
app.include_router(v1)
app.include_router(webhook_router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "unexpected failure", "code": "internal"},
    )


@app.get("/health", include_in_schema=False)
async def root_health() -> dict[str, str]:
    return {"status": "ok"}
