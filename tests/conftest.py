from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Base, Currency, Payment, PaymentStatus
from app.schemas.payment import PaymentCreate

TEST_API_KEY = "test-api-key"


@pytest.fixture(autouse=True)
def test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    monkeypatch.setenv("ENABLE_OUTBOX_WORKER", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    monkeypatch.setenv("GATEWAY_DELAY_MIN", "0")
    monkeypatch.setenv("GATEWAY_DELAY_MAX", "0")
    monkeypatch.setenv("PAYMENT_SUCCESS_RATE", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


def auth_headers(idempotency_key: str | None = "key-1") -> dict[str, str]:
    headers = {"X-API-Key": TEST_API_KEY}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def payment_payload(**overrides) -> dict:
    body = {
        "amount": "100.50",
        "currency": "RUB",
        "description": "Test payment",
        "metadata": {"order_id": "42"},
        "webhook_url": "https://example.com/webhook",
    }
    body.update(overrides)
    return body


def make_create_schema(**overrides) -> PaymentCreate:
    data = payment_payload(**overrides)
    return PaymentCreate(
        amount=Decimal(str(data["amount"])),
        currency=Currency(data["currency"]),
        description=data["description"],
        metadata=data["metadata"],
        webhook_url=data["webhook_url"],
    )


async def insert_payment(
    session: AsyncSession,
    *,
    idempotency_key: str = "key-1",
    status: PaymentStatus | None = None,
    **payload_overrides,
) -> Payment:
    from app.services.payments import create_payment

    payload = make_create_schema(**payload_overrides)
    payment = await create_payment(session, payload, idempotency_key=idempotency_key)
    if status is not None:
        payment.status = status
        await session.commit()
        await session.refresh(payment)
    return payment
