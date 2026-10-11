import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker import PAYMENTS_EXCHANGE, PAYMENTS_NEW_QUEUE, broker
from app.config import Settings
from app.models.outbox import OutboxEvent

logger = logging.getLogger(__name__)


async def publish_pending_events(
    session: AsyncSession,
    batch_size: int,
) -> int:
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at)
        .limit(batch_size)
    )
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    result = await session.execute(stmt)
    events = list(result.scalars())
    if not events:
        return 0

    published = 0
    for event in events:
        await broker.publish(
            event.payload,
            queue=PAYMENTS_NEW_QUEUE,
            exchange=PAYMENTS_EXCHANGE,
            persist=True,
        )
        event.published_at = datetime.now(UTC)
        published += 1

    await session.commit()
    logger.info("Published %s outbox event(s)", published)
    return published


async def run_outbox_worker(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    logger.info("Outbox worker started")
    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                published = await publish_pending_events(session, settings.outbox_batch_size)
        except Exception:
            logger.exception("Outbox worker iteration failed")
            published = 0

        timeout = 0.05 if published else settings.outbox_poll_interval_seconds
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except TimeoutError:
            continue
    logger.info("Outbox worker stopped")
