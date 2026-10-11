from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session


async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not x_api_key or x_api_key != get_settings().api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[None, Depends(require_api_key)]
