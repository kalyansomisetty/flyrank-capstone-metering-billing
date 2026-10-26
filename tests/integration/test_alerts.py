from datetime import UTC, date, datetime
from threading import Barrier, Lock, Thread
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AlertOutbox, ApiKey, Plan, QuotaState, Subscription, Tenant, UsageEvent
from app.schemas.generate import GenerateRequest
from app.services.alerts import _claim_alert, process_one_alert
from app.services.generation import process_generation_request


def create_tenant(
    db_session: Session,
    *,
    api_call_limit: int = 100,
    ai_token_limit: int = 100,
) -> UUID:
    tenant = Tenant(name=f"Alert Integration Tenant {uuid4()}")
    plan = Plan(
        name=f"Alert Test Plan {uuid4()}",
        api_call_limit=api_call_limit,
        ai_token_limit=ai_token_limit,
    )
    db_session.add_all([tenant, plan])
    db_session.flush()
    db_session.add(Subscription(tenant_id=tenant.id, plan_id=plan.id, status="active"))
    db_session.flush()
    return tenant.id


def alert_count(db_session: Session, tenant_id: UUID, usage_type: str) -> int:
    return (
        db_session.scalar(
            select(func.count(AlertOutbox.id)).where(
                AlertOutbox.tenant_id == tenant_id,
                AlertOutbox.usage_type == usage_type,
            )
        )
        or 0
    )


def request(*, input_tokens: int = 40, output_tokens: int = 40) -> GenerateRequest:
    return GenerateRequest(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        reasoning_tokens=0,
    )


def test_usage_crossing_creates_each_threshold_alert_once(db_session: Session) -> None:
    tenant_id = create_tenant(db_session, api_call_limit=2, ai_token_limit=200)

    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request(),
        idempotency_key="alert-first",
    )
    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request(),
        idempotency_key="alert-second",
    )

    assert alert_count(db_session, tenant_id, "api_calls") == 1
    assert alert_count(db_session, tenant_id, "ai_tokens") == 1
    assert (
        db_session.scalar(
            select(QuotaState).where(QuotaState.tenant_id == tenant_id)
        ).ai_tokens_used
        == 160
    )


def test_ai_token_threshold_crossing_creates_one_alert(db_session: Session) -> None:
    tenant_id = create_tenant(db_session, api_call_limit=100, ai_token_limit=100)

    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request(),
        idempotency_key="ai-alert-first",
    )

    assert alert_count(db_session, tenant_id, "ai_tokens") == 1


def test_alert_creation_rolls_back_with_usage_transaction(db_session: Session) -> None:
    tenant_id = create_tenant(db_session, api_call_limit=1, ai_token_limit=100)

    process_generation_request(
        db_session,
        tenant_id=tenant_id,
        request=request(),
        idempotency_key="alert-rollback-first",
    )

    with pytest.raises(HTTPException):
        process_generation_request(
            db_session,
            tenant_id=tenant_id,
            request=request(),
            idempotency_key="alert-rollback-over-limit",
        )

    assert alert_count(db_session, tenant_id, "api_calls") == 1
    assert (
        db_session.scalar(
            select(func.count(UsageEvent.id)).where(UsageEvent.tenant_id == tenant_id)
        )
        == 1
    )


class CountingAdapter:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.lock = Lock()
        self.calls = 0

    def deliver(self, **_kwargs) -> None:
        with self.lock:
            self.calls += 1
        self.barrier.wait(timeout=5)


def test_two_workers_claim_one_alert(test_engine) -> None:
    worker_sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    setup_session = worker_sessions()
    tenant_id = create_tenant(setup_session)
    alert = AlertOutbox(
        tenant_id=tenant_id,
        billing_month=date(datetime.now(UTC).year, datetime.now(UTC).month, 1),
        usage_type="api_calls",
        threshold=80,
        payload={"usage_type": "api_calls"},
        status="pending",
        attempts=0,
        available_at=None,
    )
    setup_session.add(alert)
    setup_session.flush()
    subscription_plan_id = setup_session.scalar(
        select(Subscription.plan_id).where(Subscription.tenant_id == tenant_id)
    )
    setup_session.commit()
    alert_id = alert.id
    setup_session.close()

    try:
        with worker_sessions() as diagnostic_session:
            persisted = diagnostic_session.scalar(
                select(AlertOutbox).where(AlertOutbox.id == alert_id)
            )
            assert persisted is not None
            assert persisted.status == "pending"
            assert persisted.attempts == 0
            assert persisted.available_at is None
            assert persisted.updated_at is not None

            diagnostic_session.rollback()
            claimed = _claim_alert(diagnostic_session)
            assert claimed is not None
            assert claimed.id == alert_id
            assert claimed.status == "processing"
            claimed.status = "pending"
            claimed.attempts = 0
            claimed.available_at = None
            diagnostic_session.commit()

        adapter = CountingAdapter(Barrier(1))
        results: list[bool] = []
        errors: list[BaseException] = []
        lock = Lock()

        def run_worker() -> None:
            try:
                with worker_sessions() as session:
                    result = process_one_alert(session, adapter)
                    with lock:
                        results.append(result)
            except Exception as exc:  # noqa: BLE001 - surface worker-thread failures in the test
                with lock:
                    errors.append(exc)

        threads = [Thread(target=run_worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert errors == []
        assert sorted(results) == [False, True]
        assert adapter.calls == 1
    finally:
        with worker_sessions() as cleanup_session:
            cleanup_session.execute(delete(AlertOutbox).where(AlertOutbox.id == alert_id))
            cleanup_session.execute(delete(Subscription).where(Subscription.tenant_id == tenant_id))
            cleanup_session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
            cleanup_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup_session.execute(delete(Plan).where(Plan.id == subscription_plan_id))
            cleanup_session.commit()
