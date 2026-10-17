from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant
from app.core.api_keys import generate_api_key, hash_api_key
from app.models.api_key import ApiKey
from app.models.tenant import Tenant


def create_tenant_with_key(
    db_session: Session,
    *,
    name: str,
    api_key: str | None = None,
    revoked: bool = False,
) -> Tenant:
    raw_key = api_key or generate_api_key()

    tenant = Tenant(name=name)
    db_session.add(tenant)
    db_session.flush()

    key_record = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        label="integration-test",
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db_session.add(key_record)
    db_session.flush()

    return tenant


def test_valid_api_key_resolves_its_tenant(db_session: Session) -> None:
    raw_key = generate_api_key()
    expected_tenant = create_tenant_with_key(
        db_session,
        name="Tenant A",
        api_key=raw_key,
    )

    tenant = get_current_tenant(api_key=raw_key, db=db_session)

    assert tenant.id == expected_tenant.id


@pytest.mark.parametrize("api_key", [None, "", "invalid-key"])
def test_missing_or_invalid_key_is_rejected(
    db_session: Session,
    api_key: str | None,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_tenant(api_key=api_key, db=db_session)

    assert exc_info.value.status_code == 401


def test_revoked_api_key_is_rejected(db_session: Session) -> None:
    raw_key = generate_api_key()
    create_tenant_with_key(
        db_session,
        name="Revoked Tenant",
        api_key=raw_key,
        revoked=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_tenant(api_key=raw_key, db=db_session)

    assert exc_info.value.status_code == 401


def test_each_api_key_resolves_only_its_own_tenant(
    db_session: Session,
) -> None:
    key_a = generate_api_key()
    key_b = generate_api_key()

    tenant_a = create_tenant_with_key(
        db_session,
        name="Tenant A",
        api_key=key_a,
    )
    tenant_b = create_tenant_with_key(
        db_session,
        name="Tenant B",
        api_key=key_b,
    )

    resolved_a = get_current_tenant(api_key=key_a, db=db_session)
    resolved_b = get_current_tenant(api_key=key_b, db=db_session)

    assert resolved_a.id == tenant_a.id
    assert resolved_b.id == tenant_b.id
    assert resolved_a.id != resolved_b.id
