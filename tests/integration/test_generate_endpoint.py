from collections.abc import Generator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.api_keys import generate_api_key, hash_api_key
from app.main import app
from app.models import ApiKey, Plan, QuotaState, Subscription, Tenant, UsageEvent


def create_subscribed_tenant(
    db_session: Session,
    *,
    api_call_limit: int = 100,
    ai_token_limit: int = 10_000,
) -> tuple[Tenant, str]:
    """Create an isolated tenant with an API key, plan, and active subscription."""
    raw_key = generate_api_key()

    tenant = Tenant(name=f"HTTP Test Tenant {uuid4()}")
    plan = Plan(
        name=f"HTTP Test Plan {uuid4()}",
        api_call_limit=api_call_limit,
        ai_token_limit=ai_token_limit,
    )
    db_session.add_all([tenant, plan])
    db_session.flush()

    db_session.add(
        ApiKey(
            tenant_id=tenant.id,
            key_hash=hash_api_key(raw_key),
            label="http-integration-test",
        )
    )
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="active",
        )
    )
    db_session.flush()

    return tenant, raw_key


@contextmanager
def create_client(db_session: Session) -> Generator[TestClient]:
    """Provide a test client using the isolated integration-test session."""

    def override_get_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def post_generate(
    client: TestClient,
    *,
    api_key: str,
    idempotency_key: str,
    input_tokens: int = 100,
    cached_input_tokens: int = 20,
    output_tokens: int = 50,
    reasoning_tokens: int = 10,
):
    """Send a generation request through the HTTP endpoint."""
    return client.post(
        "/generate",
        headers={
            "X-API-Key": api_key,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
        },
    )


def test_generate_endpoint_returns_usage_response(
    db_session: Session,
) -> None:
    _, raw_key = create_subscribed_tenant(db_session)

    with create_client(db_session) as client:
        response = post_generate(
            client,
            api_key=raw_key,
            idempotency_key="http-success-001",
        )

    assert response.status_code == 200
    assert response.json() == {
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 50,
        "reasoning_tokens": 10,
        "billable_tokens": 150,
        "cost_micro_units": 285,
    }


def test_generate_endpoint_rejects_missing_api_key(
    db_session: Session,
) -> None:
    with create_client(db_session) as client:
        response = client.post(
            "/generate",
            headers={"Idempotency-Key": "http-no-key-001"},
            json={
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 50,
                "reasoning_tokens": 10,
            },
        )

    assert response.status_code == 401


def test_generate_endpoint_rejects_missing_idempotency_key(
    db_session: Session,
) -> None:
    _, raw_key = create_subscribed_tenant(db_session)

    with create_client(db_session) as client:
        response = client.post(
            "/generate",
            headers={"X-API-Key": raw_key},
            json={
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 50,
                "reasoning_tokens": 10,
            },
        )

    assert response.status_code == 422


def test_generate_endpoint_rejects_invalid_token_breakdown(
    db_session: Session,
) -> None:
    _, raw_key = create_subscribed_tenant(db_session)

    with create_client(db_session) as client:
        response = client.post(
            "/generate",
            headers={
                "X-API-Key": raw_key,
                "Idempotency-Key": "http-invalid-payload-001",
            },
            json={
                "input_tokens": 10,
                "cached_input_tokens": 11,
                "output_tokens": 5,
                "reasoning_tokens": 2,
            },
        )

    assert response.status_code == 422


def test_generate_endpoint_rejects_unknown_api_key(
    db_session: Session,
) -> None:
    with create_client(db_session) as client:
        response = post_generate(
            client,
            api_key="invalid-key",
            idempotency_key="http-invalid-key-001",
        )

    assert response.status_code == 401


def test_generate_endpoint_is_idempotent_over_http(
    db_session: Session,
) -> None:
    tenant, raw_key = create_subscribed_tenant(db_session)

    with create_client(db_session) as client:
        first_response = post_generate(
            client,
            api_key=raw_key,
            idempotency_key="http-idempotency-001",
        )
        second_response = post_generate(
            client,
            api_key=raw_key,
            idempotency_key="http-idempotency-001",
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()

    events = db_session.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id)).all()
    assert len(events) == 1

    quota = db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant.id))
    assert quota is not None
    assert quota.api_calls_used == 1
    assert quota.ai_tokens_used == 150
    assert quota.cost_micro_units == 285


def test_generate_endpoint_rejects_request_over_quota(
    db_session: Session,
) -> None:
    tenant, raw_key = create_subscribed_tenant(
        db_session,
        api_call_limit=1,
        ai_token_limit=10_000,
    )

    with create_client(db_session) as client:
        first_response = post_generate(
            client,
            api_key=raw_key,
            idempotency_key="http-quota-001",
        )
        second_response = post_generate(
            client,
            api_key=raw_key,
            idempotency_key="http-quota-002",
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 429

    error = second_response.json()
    assert error["detail"]["message"] == "Monthly usage quota exceeded."
    assert error["detail"]["quota"] == "api_calls"
    assert error["detail"]["used"] == 1
    assert error["detail"]["limit"] == 1
    assert error["detail"]["requested"] == 1
    assert error["detail"]["period_ends_at"].endswith("T00:00:00+00:00")

    retry_after = int(second_response.headers["Retry-After"])
    assert retry_after >= 0

    events = db_session.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id)).all()
    assert len(events) == 1

    quota = db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant.id))
    assert quota is not None
    assert quota.api_calls_used == 1
    assert quota.ai_tokens_used == 150
    assert quota.cost_micro_units == 285
