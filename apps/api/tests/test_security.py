import logging

from nexus.core.logging import RedactingFilter, redact
from nexus.core.security import verify_webhook_signature


def test_redact_token_patterns() -> None:
    assert redact("token ghp_abc123XYZ hidden") == "token [REDACTED] hidden"
    assert redact("Authorization: Bearer secret-value here") == "[REDACTED] here"
    assert redact("api_key=supersecret1 x") == "[REDACTED] x"
    assert redact("plain log line") == "plain log line"


def test_webhook_verify() -> None:
    body = b'{"a":1}'
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(b"s3", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, "s3") is True
    assert verify_webhook_signature(body, sig, "wrong") is False
    assert verify_webhook_signature(body, "bad", "s3") is False


def test_redacting_filter_preserves_non_string_args() -> None:
    # Regression: filter must not str()-ify ints (breaks %d log formatting).
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "HTTP %s %d", ("GET", 200), None)
    assert RedactingFilter().filter(record) is True
    assert record.args == ("GET", 200)
    assert record.getMessage() == "HTTP GET 200"


def test_redacting_filter_redacts_string_args() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token %s", ("ghp_abc123XYZ",), None)
    assert RedactingFilter().filter(record) is True
    assert record.args == ("[REDACTED]",)
