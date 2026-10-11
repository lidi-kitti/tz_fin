import asyncio
import logging

from faststream import FastStream

from app.broker import broker, declare_topology
from app.consumer import handle_payment  # noqa: F401
from app.db import configure_engine, dispose_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastStream(broker)


@app.after_startup
async def on_startup() -> None:
    configure_engine()
    await declare_topology()
    logger.info("Payment consumer started")


@app.after_shutdown
async def on_shutdown() -> None:
    await dispose_engine()
    logger.info("Payment consumer stopped")


def main() -> None:
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
