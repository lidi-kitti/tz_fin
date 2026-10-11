import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PaymentStatus
from app.models.outbox import OutboxEvent
from app.models.payment import Payment
from app.schemas.payment import PaymentCreate, PaymentEvent, PaymentResponse
from app.services.gateway import PaymentGateway
from app.services.webhook import WebhookSender


class PaymentNotFoundError(Exception):
    pass


async def create_payment(
    session: AsyncSession,
    data: PaymentCreate,
    idempotency_key: str,
) -> Payment:
    existing = await _get_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment = Payment(
        id=uuid.uuid4(),
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        extra_metadata=data.metadata,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url=str(data.webhook_url),
    )
    session.add(payment)
    session.add(
        OutboxEvent(
            event_type="payment.created",
            payload=PaymentEvent(payment_id=payment.id).model_dump(mode="json"),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _get_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise
        return existing

    await session.refresh(payment)
    return payment


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFoundError(str(payment_id))
    return payment


async def process_payment(
    session: AsyncSession,
    event: PaymentEvent,
    gateway: PaymentGateway,
    webhook_sender: WebhookSender,
) -> Payment:
    payment = await session.get(Payment, event.payment_id)
    if payment is None:
        raise PaymentNotFoundError(str(event.payment_id))

    if payment.status == PaymentStatus.PENDING:
        payment.status = await gateway.charge()
        payment.processed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(payment)

    await webhook_sender.send(payment)
    return payment


def to_created_response(payment: Payment) -> dict:
    return {
        "payment_id": payment.id,
        "status": payment.status,
        "created_at": payment.created_at,
    }


def to_payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.extra_metadata or {},
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )


async def _get_by_idempotency_key(session: AsyncSession, key: str) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.idempotency_key == key))
    return result.scalar_one_or_none()
