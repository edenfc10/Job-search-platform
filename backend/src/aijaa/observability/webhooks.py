"""Signed webhook emitter to the operator client. If no webhook URL is
configured, events are logged only (useful for local QA)."""

import hashlib
import hmac
import json

import httpx
import structlog

from aijaa.core.config import get_settings
from aijaa.core.models import utcnow

log = structlog.get_logger()


async def emit(event_type: str, payload: dict) -> bool:
    settings = get_settings()
    body = json.dumps(
        {"event": event_type, "at": utcnow().isoformat(), "data": payload}, sort_keys=True
    )
    signature = hmac.new(
        settings.webhook_signing_secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    if not settings.operator_webhook_url:
        log.info("webhook_local_only", event_type=event_type, payload=payload)
        return True
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    settings.operator_webhook_url,
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-aijaa-signature": signature,
                    },
                )
                if resp.status_code < 300:
                    return True
            except httpx.HTTPError:
                pass
            log.warning("webhook_delivery_failed", event_type=event_type, attempt=attempt)
    return False
