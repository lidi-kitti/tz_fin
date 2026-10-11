from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OutboxEvent
from app.services.outbox import publish_pending_events
from tests.conftest import insert_payment


async def test_outbox_row_created_with_payment(session: AsyncSession) -> None:
    payment = await insert_payment(session)
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].published_at is None
    assert events[0].payload["payment_id"] == str(payment.id)


async def test_publish_pending_events_marks_published(
    session: AsyncSession,
) -> None:
    await insert_payment(session)
    with patch("app.services.outbox.broker.publish", new_callable=AsyncMock) as publish:
        count = await publish_pending_events(session, batch_size=10)

    assert count == 1
    publish.assert_awaited_once()
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.published_at is not None


async def test_publish_pending_events_skips_already_published(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await insert_payment(session)
        event = (await session.execute(select(OutboxEvent))).scalar_one()
        event.published_at = datetime.now(UTC)
        await session.commit()

    async with session_factory() as session:
        with patch("app.services.outbox.broker.publish", new_callable=AsyncMock) as publish:
            count = await publish_pending_events(session, batch_size=10)

    assert count == 0
    publish.assert_not_awaited()
