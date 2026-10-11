from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import get_settings

PAYMENTS_EXCHANGE = RabbitExchange(
    "payments",
    type=ExchangeType.DIRECT,
    durable=True,
)

DLX_EXCHANGE = RabbitExchange(
    "payments.dlx",
    type=ExchangeType.DIRECT,
    durable=True,
)

PAYMENTS_NEW_QUEUE = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key="payments.new",
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.dlq",
    },
)

PAYMENTS_DLQ = RabbitQueue(
    "payments.dlq",
    durable=True,
    routing_key="payments.dlq",
)

RETRY_DELAYS_MS = (1_000, 2_000, 4_000)

RETRY_QUEUES = tuple(
    RabbitQueue(
        f"payments.retry.{attempt}",
        durable=True,
        routing_key=f"payments.retry.{attempt}",
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": "payments",
            "x-dead-letter-routing-key": "payments.new",
        },
    )
    for attempt, delay_ms in enumerate(RETRY_DELAYS_MS, start=1)
)

broker = RabbitBroker(get_settings().rabbitmq_url, fail_fast=False)


async def declare_topology() -> None:
    """Declare exchanges, queues and bindings used by publisher and consumer."""
    await broker.declare_exchange(PAYMENTS_EXCHANGE)
    await broker.declare_exchange(DLX_EXCHANGE)
    await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    dlq = await broker.declare_queue(PAYMENTS_DLQ)
    dlx = await broker.declare_exchange(DLX_EXCHANGE)
    await dlq.bind(dlx, routing_key=PAYMENTS_DLQ.routing())
    for queue in RETRY_QUEUES:
        await broker.declare_queue(queue)


def retry_queue_for_attempt(failed_attempt: int) -> RabbitQueue | None:
    """Queue that holds a failed message until the next attempt, or None for DLQ."""
    index = failed_attempt - 1
    if 0 <= index < len(RETRY_QUEUES):
        return RETRY_QUEUES[index]
    return None
