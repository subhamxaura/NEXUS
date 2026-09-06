"""GitHub webhooks (signature-verified). Mounted at /webhooks/github."""

from fastapi import APIRouter, Header, HTTPException, Request

from nexus.core.config import settings
from nexus.core.database import SessionLocal
from nexus.core.security import verify_webhook_signature
from nexus.services import webhooks as webhook_service

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/github")
async def github_webhook(
    request: Request, x_hub_signature_256: str = Header(default="")
) -> dict[str, object]:
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=400, detail="webhook not configured")
    body = await request.body()
    if not verify_webhook_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")
    event = request.headers.get("x-github-event", "")
    try:
        import json

        payload = json.loads(body.decode())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid JSON") from e
    if event == "push":
        async with SessionLocal() as session:
            return await webhook_service.handle_push(session, payload)
    return {"status": "acknowledged", "event": event}
