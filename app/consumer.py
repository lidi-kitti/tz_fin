import logging

from faststream import AckPolicy
from faststream.rabbit import RabbitMessage

from app.broker import (
    DLX_EXCHANGE,
    PAYMENTS_DLQ,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    broker,
    retry_queue_for_attempt,
)
from app.config import get_settings
from app.db import get_session_factory
from app.schemas.payment import PaymentEvent
from app.services.gateway import PaymentGateway
from app.services.payments import PaymentNotFoundError, process_payment
from app.services.webhook import WebhookSender

logger = logging.getLogger(__name__)

ATTEMPT_HEADER = "x-attempt"


@broker.subscriber(
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_EXCHANGE,
    ack_policy=AckPolicy.REJECT_ON_ERROR,
)
async def handle_payment(event: PaymentEvent, message: RabbitMessage) -> None:
    """Single consumer: emulate gateway, update DB, send webhook, retry/DLQ."""
    settings = get_settings()
    attempt = _current_attempt(event, message)
    event.attempt = attempt
    logger.info("Processing payment_id=%s attempt=%s", event.payment_id, attempt)

    factory = get_session_factory()
    try:
        async with factory() as session:
            await process_payment(
                session,
                event,
                gateway=PaymentGateway(settings),
                webhook_sender=WebhookSender(settings),
            )
    except PaymentNotFoundError:
        logger.error("Payment %s not found, sending to DLQ", event.payment_id)
        await _publish_dlq(event, attempt, "payment_not_found")
        return
    except Exception:
        logger.exception("Payment %s failed on attempt %s", event.payment_id, attempt)
        await _retry_or_dlq(event, attempt)
        return

    logger.info("Payment %s processed on attempt %s", event.payment_id, attempt)


def _current_attempt(event: PaymentEvent, message: RabbitMessage) -> int:
    header = (message.headers or {}).get(ATTEMPT_HEADER)
    if header is not None:
        return int(header)
    return event.attempt


async def _retry_or_dlq(event: PaymentEvent, attempt: int) -> None:
    retry_queue = retry_queue_for_attempt(attempt)
    if retry_queue is None:
        await _publish_dlq(event, attempt, "max_attempts_exceeded")
        return

    next_event = event.model_copy(update={"attempt": attempt + 1})
    await broker.publish(
        next_event,
        queue=retry_queue,
        persist=True,
        headers={ATTEMPT_HEADER: attempt + 1},
    )
    logger.warning(
        "Scheduled retry payment_id=%s next_attempt=%s queue=%s",
        event.payment_id,
        attempt + 1,
        retry_queue.name,
    )


async def _publish_dlq(event: PaymentEvent, attempt: int, reason: str) -> None:
    await broker.publish(
        event,
        queue=PAYMENTS_DLQ,
        exchange=DLX_EXCHANGE,
        persist=True,
        headers={ATTEMPT_HEADER: attempt, "x-failure-reason": reason},
    )
    logger.error(
        "Published to DLQ payment_id=%s attempt=%s reason=%s",
        event.payment_id,
        attempt,
        reason,
    )
