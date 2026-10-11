from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker import RETRY_QUEUES, retry_queue_for_attempt
from app.config import get_settings
from app.models import PaymentStatus
from app.schemas.payment import PaymentEvent
from app.services.gateway import PaymentGateway
from app.services.payments import process_payment
from app.services.webhook import WebhookDeliveryError, WebhookSender
from tests.conftest import insert_payment


class ImmediateGateway(PaymentGateway):
    def __init__(self, status: PaymentStatus = PaymentStatus.SUCCEEDED) -> None:
        self.status = status
        super().__init__(get_settings())

    async def charge(self) -> PaymentStatus:
        return self.status


async def test_process_success_updates_status_and_sends_webhook(
    session: AsyncSession,
) -> None:
    payment = await insert_payment(session)
    sender = WebhookSender(get_settings(), client=AsyncMock())
    sender._client.post = AsyncMock(return_value=httpx.Response(200, request=_req()))

    result = await process_payment(
        session,
        PaymentEvent(payment_id=payment.id),
        gateway=ImmediateGateway(PaymentStatus.SUCCEEDED),
        webhook_sender=sender,
    )

    assert result.status is PaymentStatus.SUCCEEDED
    assert result.processed_at is not None
    sender._client.post.assert_awaited_once()
    payload = sender._client.post.await_args.kwargs["json"]
    assert payload["payment_id"] == str(payment.id)
    assert payload["status"] == "succeeded"


async def test_gateway_failure_marks_payment_failed(session: AsyncSession) -> None:
    payment = await insert_payment(session)
    sender = WebhookSender(get_settings(), client=AsyncMock())
    sender._client.post = AsyncMock(return_value=httpx.Response(200, request=_req()))

    result = await process_payment(
        session,
        PaymentEvent(payment_id=payment.id),
        gateway=ImmediateGateway(PaymentStatus.FAILED),
        webhook_sender=sender,
    )

    assert result.status is PaymentStatus.FAILED
    sender._client.post.assert_awaited_once()


async def test_already_processed_payment_skips_gateway(session: AsyncSession) -> None:
    payment = await insert_payment(session, status=PaymentStatus.SUCCEEDED)
    payment.processed_at = datetime.now(UTC)
    await session.commit()

    gateway = ImmediateGateway(PaymentStatus.FAILED)
    gateway.charge = AsyncMock(side_effect=AssertionError("gateway must not run"))
    sender = WebhookSender(get_settings(), client=AsyncMock())
    sender._client.post = AsyncMock(return_value=httpx.Response(200, request=_req()))

    result = await process_payment(
        session,
        PaymentEvent(payment_id=payment.id, attempt=2),
        gateway=gateway,
        webhook_sender=sender,
    )
    assert result.status is PaymentStatus.SUCCEEDED
    sender._client.post.assert_awaited_once()


async def test_webhook_retries_then_succeeds(session: AsyncSession, monkeypatch) -> None:
    payment = await insert_payment(session)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.services.webhook.asyncio.sleep", fake_sleep)

    client = AsyncMock()
    client.post = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError("fail", request=_req(), response=httpx.Response(500)),
            httpx.HTTPStatusError("fail", request=_req(), response=httpx.Response(500)),
            httpx.Response(200, request=_req()),
        ]
    )
    sender = WebhookSender(get_settings(), client=client)

    await process_payment(
        session,
        PaymentEvent(payment_id=payment.id),
        gateway=ImmediateGateway(),
        webhook_sender=sender,
    )
    assert client.post.await_count == 3
    assert sleeps == [1, 2]


async def test_webhook_exhausted_retries_raise(session: AsyncSession, monkeypatch) -> None:
    payment = await insert_payment(session)
    monkeypatch.setattr("app.services.webhook.asyncio.sleep", AsyncMock())
    client = AsyncMock()
    client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
    sender = WebhookSender(get_settings(), client=client)

    with pytest.raises(WebhookDeliveryError):
        await process_payment(
            session,
            PaymentEvent(payment_id=payment.id),
            gateway=ImmediateGateway(),
            webhook_sender=sender,
        )
    assert client.post.await_count == get_settings().max_attempts


async def test_unknown_payment_is_not_silently_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.services.payments import PaymentNotFoundError

    async with session_factory() as session:
        with pytest.raises(PaymentNotFoundError):
            await process_payment(
                session,
                PaymentEvent(payment_id=uuid4()),
                gateway=ImmediateGateway(),
                webhook_sender=WebhookSender(get_settings(), client=AsyncMock()),
            )


def test_retry_queues_cover_three_attempts_then_dlq() -> None:
    assert retry_queue_for_attempt(1) is RETRY_QUEUES[0]
    assert retry_queue_for_attempt(2) is RETRY_QUEUES[1]
    assert retry_queue_for_attempt(3) is RETRY_QUEUES[2]
    assert retry_queue_for_attempt(4) is None
    assert [q.arguments["x-message-ttl"] for q in RETRY_QUEUES] == [1000, 2000, 4000]


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://example.com/webhook")
