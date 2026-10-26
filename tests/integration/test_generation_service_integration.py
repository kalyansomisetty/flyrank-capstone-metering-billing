from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Plan, QuotaState, Subscription, Tenant, UsageEvent
from app.schemas.generate import GenerateRequest
from app.services.generation import process_generation_request


def create_subscribed_tenant(
    db_session: Session,
    *,
    api_call_limit: int = 100,
    ai_token_limit: int = 100_000,
    status: str = "active",
) -> UUID:
    tenant = Tenant(name="Generation Integration Test Tenant")
    plan = Plan(
        name=f"Generation Test Plan {uuid4()}",
        api_call_limit=api_call_limit,
        ai_token_limit=ai_token_limit,
    )
    db_session.add_all([tenant, plan])
    db_session.flush()

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status=status,
    )
    db_session.add(subscription)
    db_session.flush()

    return tenant.id


def sample_request() -> GenerateRequest:
    return GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )


def count_usage_events(db_session: Session, tenant_id: UUID) -> int:
    return (
        db_session.scalar(
            select(func.count()).select_from(UsageEvent).where(UsageEvent.tenant_id == tenant_id)
        )
        or 0
    )


def test_successful_request_records_usage(db_session: Session) -> None:
    tenant_id = create_subscribed_tenant(db_session)

    response = process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=sample_request(),
        idempotency_key="generation-success-1",
    )

    assert response.billable_tokens == 150
    assert response.cost_micro_units == 285
    assert count_usage_events(db_session, tenant_id) == 1

    quota = db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant_id))
    assert quota is not None
    assert quota.api_calls_used == 1
    assert quota.ai_tokens_used == 150
    assert quota.cost_micro_units == 285


def test_same_key_and_payload_returns_saved_response(
    db_session: Session,
) -> None:
    tenant_id = create_subscribed_tenant(db_session)
    request = sample_request()

    first = process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request,
        idempotency_key="generation-replay-1",
    )
    replay = process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request,
        idempotency_key="generation-replay-1",
    )

    assert replay == first
    assert count_usage_events(db_session, tenant_id) == 1

    quota = db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant_id))
    assert quota is not None
    assert quota.api_calls_used == 1
    assert quota.ai_tokens_used == 150


def test_same_key_with_different_payload_returns_conflict(
    db_session: Session,
) -> None:
    tenant_id = create_subscribed_tenant(db_session)

    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=sample_request(),
        idempotency_key="generation-conflict-1",
    )

    changed_request = GenerateRequest(
        input_tokens=101,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )

    with pytest.raises(HTTPException) as exc_info:
        process_generation_request(
            db_session,
            tenant_id=tenant_id,
            request=changed_request,
            idempotency_key="generation-conflict-1",
        )

    assert exc_info.value.status_code == 409
    assert count_usage_events(db_session, tenant_id) == 1


def test_exact_quota_limit_is_allowed_but_next_call_is_rejected(
    db_session: Session,
) -> None:
    tenant_id = create_subscribed_tenant(
        db_session,
        api_call_limit=1,
        ai_token_limit=150,
    )

    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=sample_request(),
        idempotency_key="generation-quota-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        process_generation_request(
            db_session,
            tenant_id=tenant_id,
            request=sample_request(),
            idempotency_key="generation-quota-2",
        )

    assert exc_info.value.status_code == 429
    assert count_usage_events(db_session, tenant_id) == 1

    quota = db_session.scalar(select(QuotaState).where(QuotaState.tenant_id == tenant_id))
    assert quota is not None
    assert quota.api_calls_used == 1
    assert quota.ai_tokens_used == 150


def test_inactive_subscription_is_rejected_without_usage(
    db_session: Session,
) -> None:
    tenant_id = create_subscribed_tenant(
        db_session,
        status="canceled",
    )

    with pytest.raises(HTTPException) as exc_info:
        process_generation_request(
            db_session,
            tenant_id=tenant_id,
            request=sample_request(),
            idempotency_key="generation-inactive-1",
        )

    assert exc_info.value.status_code == 402
    assert count_usage_events(db_session, tenant_id) == 0
