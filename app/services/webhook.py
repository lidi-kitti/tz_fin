import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.models.payment import Payment

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Raised when a webhook cannot be delivered after all retries."""


class WebhookSender:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def send(self, payment: Payment) -> None:
        payload = {
            "payment_id": str(payment.id),
            "status": payment.status.value,
            "processed_at": _serialize_dt(payment.processed_at),
        }
        last_error: Exception | None = None
        attempts = self._settings.max_attempts

        for attempt in range(1, attempts + 1):
            try:
                await self._post(str(payment.webhook_url), payload)
                logger.info(
                    "Webhook delivered payment_id=%s status=%s attempt=%s",
                    payment.id,
                    payment.status,
                    attempt,
                )
                return
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                last_error = exc
                logger.warning(
                    "Webhook attempt %s/%s failed payment_id=%s: %s",
                    attempt,
                    attempts,
                    payment.id,
                    exc,
                )
                if attempt < attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise WebhookDeliveryError(
            f"Failed to deliver webhook for payment {payment.id} after {attempts} attempts"
        ) from last_error

    async def _post(self, url: str, payload: dict) -> None:
        if self._client is not None:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            return

        timeout = httpx.Timeout(self._settings.webhook_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
