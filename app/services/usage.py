from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.quota_state import QuotaState
from app.models.subscription import Subscription
from app.schemas.usage import UsageResponse


def get_tenant_usage(db: Session, *, tenant_id: UUID) -> UsageResponse:
    """Return the authenticated tenant's usage for the current UTC month."""
    now = datetime.now(UTC)
    billing_month = date(now.year, now.month, 1)

    subscription_and_plan = db.execute(
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(Subscription.tenant_id == tenant_id)
    ).one_or_none()

    if subscription_and_plan is None:
        raise HTTPException(
            status_code=402,
            detail="No subscription is configured for this tenant.",
        )

    subscription, plan = subscription_and_plan

    quota = db.scalar(
        select(QuotaState).where(
            QuotaState.tenant_id == tenant_id,
            QuotaState.billing_month == billing_month,
        )
    )

    return UsageResponse(
        billing_month=billing_month,
        plan_name=plan.name,
        subscription_status=subscription.status,
        api_calls_used=quota.api_calls_used if quota else 0,
        api_call_limit=plan.api_call_limit,
        ai_tokens_used=quota.ai_tokens_used if quota else 0,
        ai_token_limit=plan.ai_token_limit,
        cost_micro_units=quota.cost_micro_units if quota else 0,
    )
