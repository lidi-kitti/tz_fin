from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OutboxEvent, Payment
from tests.conftest import TEST_API_KEY, auth_headers, payment_payload


async def test_health_does_not_require_api_key(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_payment_requires_api_key(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers={"Idempotency-Key": "k1"},
    )
    assert response.status_code == 401


async def test_create_payment_requires_idempotency_key(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert response.status_code == 422


async def test_create_payment_returns_202(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers("create-1"),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert "payment_id" in body
    assert "created_at" in body

    async with session_factory() as session:
        payment = await session.get(Payment, UUID(body["payment_id"]))
        assert payment is not None
        events = (await session.execute(select(OutboxEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "payment.created"
        assert events[0].payload["payment_id"] == body["payment_id"]
        assert events[0].published_at is None


async def test_idempotency_returns_same_payment(client: AsyncClient) -> None:
    headers = auth_headers("same-key")
    first = await client.post("/api/v1/payments", json=payment_payload(), headers=headers)
    second = await client.post(
        "/api/v1/payments",
        json=payment_payload(description="changed"),
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert first.json()["created_at"] == second.json()["created_at"]


async def test_get_payment(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers("get-1"),
    )
    payment_id = created.json()["payment_id"]
    response = await client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["payment_id"] == payment_id
    assert body["amount"] == "100.50"
    assert body["currency"] == "RUB"
    assert body["status"] == "pending"
    assert body["idempotency_key"] == "get-1"
    assert body["metadata"] == {"order_id": "42"}


async def test_get_payment_not_found(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/payments/{uuid4()}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert response.status_code == 404


async def test_invalid_amount_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(amount="0"),
        headers=auth_headers("bad-amount"),
    )
    assert response.status_code == 422
