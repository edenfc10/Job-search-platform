"""Structured logging helpers."""

from __future__ import annotations

from typing import Any

import structlog

REDACT_KEYS = {"email", "phone", "address", "api_key", "anthropic_api_key", "webhook_signing_secret"}


def redact_processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("[redacted]" if k.lower() in REDACT_KEYS else scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(event_dict)


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_processor,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )
