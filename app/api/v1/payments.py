from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import AuthDep, SessionDep
from app.schemas.payment import PaymentCreate, PaymentCreatedResponse, PaymentResponse
from app.services.payments import (
    PaymentNotFoundError,
    create_payment,
    get_payment,
    to_created_response,
    to_payment_response,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreatedResponse,
)
async def create_payment_endpoint(
    payload: PaymentCreate,
    session: SessionDep,
    _: AuthDep,
    idempotency_key: Annotated[
        str,
        Header(min_length=1, max_length=255),
    ],
) -> PaymentCreatedResponse:
    payment = await create_payment(session, payload, idempotency_key)
    return PaymentCreatedResponse.model_validate(to_created_response(payment))


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment_endpoint(
    payment_id: UUID,
    session: SessionDep,
    _: AuthDep,
) -> PaymentResponse:
    try:
        payment = await get_payment(session, payment_id)
    except PaymentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        ) from exc
    return to_payment_response(payment)
