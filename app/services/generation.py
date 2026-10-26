"""Helpers and transactional service for billable generation requests."""

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.quota_state import QuotaState
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services.alerts import enqueue_threshold_alerts
from app.services.pricing import calculate_billable_tokens, calculate_cost_micro_units


def request_fingerprint(request: GenerateRequest) -> str:
    """Return a stable SHA-256 fingerprint for a validated request."""
    canonical_payload = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def process_generation_request(
    db: Session,
    *,
    tenant_id: UUID,
    request: GenerateRequest,
    idempotency_key: str,
) -> GenerateResponse:
    """Record billable usage once, enforcing tenant and monthly plan limits."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="Idempotency-Key cannot be empty.")

    if idempotency_key != idempotency_key.strip() or len(idempotency_key) > 255:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be trimmed and at most 255 characters.",
        )

    fingerprint = request_fingerprint(request)
    response: GenerateResponse

    # The savepoint lets a rejected request roll back its work without
    # unnecessarily rolling back a transaction owned by the caller.
    with db.begin_nested():
        # Serializing requests for the same tenant also protects idempotency
        # across a billing-month boundary.
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        if tenant is None:
            raise HTTPException(status_code=401, detail="Tenant not found.")

        existing_event = db.scalar(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.idempotency_key == idempotency_key,
            )
        )

        if existing_event is not None:
            if existing_event.payload_fingerprint != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different payload.",
                )

            response = GenerateResponse.model_validate(existing_event.response_snapshot)
        else:
            subscription = db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant_id).with_for_update()
            )

            if subscription is None or subscription.status not in {"active", "trialing"}:
                raise HTTPException(
                    status_code=402,
                    detail="An active subscription is required.",
                )

            plan = db.get(Plan, subscription.plan_id)
            if plan is None:
                raise HTTPException(
                    status_code=402,
                    detail="The subscription plan is unavailable.",
                )

            now = datetime.now(UTC)
            billing_month = date(now.year, now.month, 1)

            # Create the tenant's monthly quota row if it doesn't exist.
            db.execute(
                pg_insert(QuotaState)
                .values(
                    tenant_id=tenant_id,
                    billing_month=billing_month,
                    api_calls_used=0,
                    ai_tokens_used=0,
                    cost_micro_units=0,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "billing_month"])
            )

            quota = db.scalar(
                select(QuotaState)
                .where(
                    QuotaState.tenant_id == tenant_id,
                    QuotaState.billing_month == billing_month,
                )
                .with_for_update()
            )
            if quota is None:
                raise RuntimeError("Could not initialize monthly quota state.")

            previous_api_calls = quota.api_calls_used
            previous_ai_tokens = quota.ai_tokens_used
            billable_tokens = calculate_billable_tokens(
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
            )

            api_calls_exceeded = quota.api_calls_used + 1 > plan.api_call_limit
            ai_tokens_exceeded = quota.ai_tokens_used + billable_tokens > plan.ai_token_limit

            if api_calls_exceeded or ai_tokens_exceeded:
                next_month = (
                    date(billing_month.year + 1, 1, 1)
                    if billing_month.month == 12
                    else date(billing_month.year, billing_month.month + 1, 1)
                )
                now = datetime.now(UTC)
                reset_at = datetime.combine(next_month, datetime.min.time(), tzinfo=UTC)
                retry_after = max(0, int((reset_at - now).total_seconds()))

                if api_calls_exceeded:
                    quota_detail = {
                        "quota": "api_calls",
                        "used": quota.api_calls_used,
                        "limit": plan.api_call_limit,
                        "requested": 1,
                    }
                else:
                    quota_detail = {
                        "quota": "ai_tokens",
                        "used": quota.ai_tokens_used,
                        "limit": plan.ai_token_limit,
                        "requested": billable_tokens,
                    }

                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Monthly usage quota exceeded.",
                        **quota_detail,
                        "period_ends_at": reset_at.isoformat(),
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            cost = calculate_cost_micro_units(
                input_tokens=request.input_tokens,
                cached_input_tokens=request.cached_input_tokens,
                output_tokens=request.output_tokens,
            )

            response = GenerateResponse(
                input_tokens=request.input_tokens,
                cached_input_tokens=request.cached_input_tokens,
                output_tokens=request.output_tokens,
                reasoning_tokens=request.reasoning_tokens,
                billable_tokens=billable_tokens,
                cost_micro_units=cost,
            )

            db.add(
                UsageEvent(
                    tenant_id=tenant_id,
                    billing_month=billing_month,
                    api_call_quantity=1,
                    input_tokens=request.input_tokens,
                    cached_input_tokens=request.cached_input_tokens,
                    output_tokens=request.output_tokens,
                    reasoning_tokens=request.reasoning_tokens,
                    payload_fingerprint=fingerprint,
                    idempotency_key=idempotency_key,
                    response_snapshot=response.model_dump(mode="json"),
                    cost_micro_units=cost,
                )
            )

            quota.api_calls_used += 1
            quota.ai_tokens_used += billable_tokens
            quota.cost_micro_units += cost
            enqueue_threshold_alerts(
                db,
                tenant_id=tenant_id,
                billing_month=billing_month,
                previous_api_calls=previous_api_calls,
                current_api_calls=quota.api_calls_used,
                api_call_limit=plan.api_call_limit,
                previous_ai_tokens=previous_ai_tokens,
                current_ai_tokens=quota.ai_tokens_used,
                ai_token_limit=plan.ai_token_limit,
            )

            # Surface database constraints before releasing the savepoint.
            db.flush()

    # In production this commits the request. The integration fixture's
    # outer transaction keeps test data isolated for rollback after each test.
    db.commit()
    return response
