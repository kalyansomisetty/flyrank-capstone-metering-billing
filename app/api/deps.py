from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.api_keys import hash_api_key
from app.db.session import get_db_session
from app.models.api_key import ApiKey
from app.models.tenant import Tenant


def get_db() -> Generator[Session]:
    yield from get_db_session()


def get_current_tenant(
    db: Annotated[Session, Depends(get_db)],
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Tenant:
    """Authenticate an API key and return its tenant."""
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key",
        )

    statement = (
        select(Tenant)
        .join(ApiKey, ApiKey.tenant_id == Tenant.id)
        .where(
            ApiKey.key_hash == hash_api_key(api_key),
            ApiKey.revoked_at.is_(None),
        )
    )

    tenant = db.scalar(statement)

    if tenant is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key",
        )

    return tenant
