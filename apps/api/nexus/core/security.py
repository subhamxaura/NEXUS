"""Auth helpers: JWT sessions + Fernet token encryption + webhook HMAC verify."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from nexus.core.config import settings

ALGORITHM = "HS256"
SESSION_TTL = timedelta(hours=12)


def create_session_token(user_id: int) -> str:
    now = datetime.now(UTC)
    token: str = jwt.encode(
        {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int((now + SESSION_TTL).timestamp()),
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    return token


def parse_session_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None


def _fernet() -> Fernet | None:
    if not settings.token_fernet_key:
        return None
    return Fernet(settings.token_fernet_key.encode())


def encrypt_token(raw: str) -> str:
    f = _fernet()
    if f is None:
        raise RuntimeError("TOKEN_FERNET_KEY not configured; refusing to store token insecurely")
    return f.encrypt(raw.encode()).decode()


def decrypt_token(enc: str) -> str:
    f = _fernet()
    if f is None:
        raise RuntimeError("TOKEN_FERNET_KEY not configured")
    try:
        return f.decrypt(enc.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("stored token undecryptable") from e


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature (`sha256=<hex>`)."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + expected, signature)
