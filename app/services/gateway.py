import asyncio
import random

from app.config import Settings
from app.models.enums import PaymentStatus


class PaymentGateway:
    """Emulates an external payment gateway: 2–5s delay, ~90% success."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def charge(self) -> PaymentStatus:
        delay = random.uniform(
            self._settings.gateway_delay_min,
            self._settings.gateway_delay_max,
        )
        await asyncio.sleep(delay)
        if random.random() < self._settings.payment_success_rate:
            return PaymentStatus.SUCCEEDED
        return PaymentStatus.FAILED
