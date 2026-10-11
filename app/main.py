import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.broker import broker, declare_topology
from app.config import get_settings
from app.db import configure_engine, dispose_engine, get_session_factory
from app.services.outbox import run_outbox_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_engine()
    stop_event = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None

    if settings.enable_outbox_worker:
        await broker.start()
        await declare_topology()
        worker_task = asyncio.create_task(
            run_outbox_worker(get_session_factory(), settings, stop_event),
            name="outbox-worker",
        )
        logger.info("API started with outbox publisher")
    else:
        logger.info("API started without outbox publisher")

    try:
        yield
    finally:
        stop_event.set()
        if worker_task is not None:
            await worker_task
        if settings.enable_outbox_worker:
            await broker.stop()
        await dispose_engine()


app = FastAPI(
    title="Payment Service",
    description="Asynchronous payment processing with Outbox, retries and DLQ",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)
