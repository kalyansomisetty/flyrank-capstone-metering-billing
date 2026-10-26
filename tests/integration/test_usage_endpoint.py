from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.api_keys import generate_api_key, hash_api_key
from app.main import app
from app.models import ApiKey, Plan, QuotaState, Subscription, Tenant


def create_subscribed_tenant(
    db_session: Session,
    *,
    status: str = "active",
    api_call_limit: int = 100,
    ai_token_limit: int = 10_000,
) -> tuple[Tenant, str, Plan]:
    raw_key = generate_api_key()
    tenant = Tenant(name=f"Usage Test Tenant {uuid4()}")
    plan = Plan(
        name=f"Usage Test Plan {uuid4()}",
        api_call_limit=api_call_limit,
        ai_token_limit=ai_token_limit,
    )
    db_session.add_all([tenant, plan])
    db_session.flush()

    db_session.add_all(
        [
            ApiKey(
                tenant_id=tenant.id,
                key_hash=hash_api_key(raw_key),
                label="usage-integration-test",
            ),
            Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status=status,
            ),
        ]
    )
    db_session.flush()
    return tenant, raw_key, plan


@contextmanager
def create_client(db_session: Session) -> Generator[TestClient]:
    def override_get_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_usage_returns_zero_for_new_tenant(db_session: Session) -> None:
    tenant, raw_key, plan = create_subscribed_tenant(db_session)

    with create_client(db_session) as client:
        response = client.get("/usage", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    assert response.json() == {
        "billing_month": date(
            datetime.now(UTC).year,
            datetime.now(UTC).month,
            1,
        ).isoformat(),
        "plan_name": plan.name,
        "subscription_status": "active",
        "api_calls_used": 0,
        "api_call_limit": 100,
        "ai_tokens_used": 0,
        "ai_token_limit": 10_000,
        "cost_micro_units": 0,
    }
    assert db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant.id)) is None


def test_usage_returns_recorded_current_month_totals(
    db_session: Session,
) -> None:
    tenant, raw_key, plan = create_subscribed_tenant(
        db_session,
        api_call_limit=500,
        ai_token_limit=50_000,
    )
    now = datetime.now(UTC)
    billing_month = date(now.year, now.month, 1)
    db_session.add(
        QuotaState(
            tenant_id=tenant.id,
            billing_month=billing_month,
            api_calls_used=7,
            ai_tokens_used=1_250,
            cost_micro_units=3_400,
        )
    )
    db_session.flush()

    with create_client(db_session) as client:
        response = client.get("/usage", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    assert response.json() == {
        "billing_month": billing_month.isoformat(),
        "plan_name": plan.name,
        "subscription_status": "active",
        "api_calls_used": 7,
        "api_call_limit": 500,
        "ai_tokens_used": 1_250,
        "ai_token_limit": 50_000,
        "cost_micro_units": 3_400,
    }


def test_usage_rejects_missing_api_key(db_session: Session) -> None:
    with create_client(db_session) as client:
        response = client.get("/usage")

    assert response.status_code == 401


def test_usage_includes_inactive_subscription_status(
    db_session: Session,
) -> None:
    _, raw_key, _ = create_subscribed_tenant(
        db_session,
        status="canceled",
    )

    with create_client(db_session) as client:
        response = client.get("/usage", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    assert response.json()["subscription_status"] == "canceled"


def test_usage_does_not_expose_another_tenants_totals(
    db_session: Session,
) -> None:
    _, key_a, _ = create_subscribed_tenant(db_session)
    tenant_b, key_b, _ = create_subscribed_tenant(db_session)
    now = datetime.now(UTC)
    billing_month = date(now.year, now.month, 1)

    db_session.add(
        QuotaState(
            tenant_id=tenant_b.id,
            billing_month=billing_month,
            api_calls_used=99,
            ai_tokens_used=9_999,
            cost_micro_units=88_888,
        )
    )
    db_session.flush()

    with create_client(db_session) as client:
        response_a = client.get("/usage", headers={"X-API-Key": key_a})
        response_b = client.get("/usage", headers={"X-API-Key": key_b})

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["api_calls_used"] == 0
    assert response_a.json()["ai_tokens_used"] == 0
    assert response_a.json()["cost_micro_units"] == 0
    assert response_b.json()["api_calls_used"] == 99
    assert response_b.json()["ai_tokens_used"] == 9_999
    assert response_b.json()["cost_micro_units"] == 88_888
