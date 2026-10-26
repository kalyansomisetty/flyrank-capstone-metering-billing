from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import AlertOutbox, Plan, QuotaState, Subscription, Tenant, UsageEvent
from app.schemas.generate import GenerateRequest
from app.services.generation import process_generation_request


def test_concurrent_requests_cannot_exceed_api_call_quota(
    test_engine,
) -> None:
    """Only one concurrent request may consume the tenant's final API call."""
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    # Create committed fixture data so independent worker connections can see it.
    with session_factory() as setup_session:
        tenant = Tenant(name=f"Concurrency Test Tenant {uuid4()}")
        plan = Plan(
            name=f"Concurrency Test Plan {uuid4()}",
            api_call_limit=1,
            ai_token_limit=10_000,
        )
        setup_session.add_all([tenant, plan])
        setup_session.flush()

        tenant_id = tenant.id
        setup_session.add(
            Subscription(
                tenant_id=tenant_id,
                plan_id=plan.id,
                status="active",
            )
        )
        setup_session.commit()

    start_barrier = Barrier(2)

    def submit_request(idempotency_key: str) -> int:
        with session_factory() as worker_session:
            start_barrier.wait(timeout=10)

            try:
                process_generation_request(
                    worker_session,
                    tenant_id=tenant_id,
                    request=GenerateRequest(
                        input_tokens=100,
                        cached_input_tokens=20,
                        output_tokens=50,
                        reasoning_tokens=10,
                    ),
                    idempotency_key=idempotency_key,
                )
                return 200
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit_request, "concurrent-request-a"),
                executor.submit(submit_request, "concurrent-request-b"),
            ]
            statuses = sorted(future.result(timeout=20) for future in futures)

        assert statuses == [200, 429]

        with session_factory() as verify_session:
            event_count = verify_session.scalar(
                select(func.count())
                .select_from(UsageEvent)
                .where(UsageEvent.tenant_id == tenant_id)
            )
            assert event_count == 1

            quota = verify_session.scalar(
                select(QuotaState).where(QuotaState.tenant_id == tenant_id)
            )
            assert quota is not None
            assert quota.api_calls_used == 1
            assert quota.ai_tokens_used == 150
            assert quota.cost_micro_units == 285

    finally:
        # Delete only records belonging to this test.
        with session_factory() as cleanup_session:
            cleanup_session.execute(delete(UsageEvent).where(UsageEvent.tenant_id == tenant_id))
            cleanup_session.execute(delete(QuotaState).where(QuotaState.tenant_id == tenant_id))
            cleanup_session.execute(delete(AlertOutbox).where(AlertOutbox.tenant_id == tenant_id))
            cleanup_session.execute(delete(Subscription).where(Subscription.tenant_id == tenant_id))
            cleanup_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup_session.execute(delete(Plan).where(Plan.id == plan.id))
            cleanup_session.commit()
