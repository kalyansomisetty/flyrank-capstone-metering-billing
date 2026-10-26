from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.stripe.client import StripeAdapter
from app.models.plan import Plan
from app.models.stripe_event import StripeEvent
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.schemas.stripe import CheckoutRequest, CheckoutResponse

SUPPORTED_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}
NON_BILLABLE_STATUSES = {
    "past_due",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "canceled",
}


class StripeWebhookError(ValueError):
    pass


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StripeWebhookError("Stripe event payload is malformed.")
    return value


def _metadata_tenant_id(metadata: Any) -> UUID | None:
    if not isinstance(metadata, dict):
        return None
    raw_tenant_id = metadata.get("tenant_id")
    if raw_tenant_id is None:
        return None
    try:
        return UUID(str(raw_tenant_id))
    except ValueError as exc:
        raise StripeWebhookError("Stripe tenant metadata is invalid.") from exc


def _event_object(event: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(event.get("data"))
    return _as_dict(data.get("object"))


def _event_created_at(event: dict[str, Any]) -> datetime:
    created = event.get("created")
    if not isinstance(created, int):
        raise StripeWebhookError("Stripe event timestamp is malformed.")
    return datetime.fromtimestamp(created, UTC)


def _subscription_price_id(subscription_data: dict[str, Any]) -> str | None:
    items = _as_dict(subscription_data.get("items"))
    data = items.get("data")
    if not isinstance(data, list) or not data:
        return None
    first_item = _as_dict(data[0])
    price = _as_dict(first_item.get("price"))
    price_id = price.get("id")
    return str(price_id) if price_id else None


def _period_end(subscription_data: dict[str, Any]) -> datetime | None:
    value = subscription_data.get("current_period_end")
    if value is None:
        return None
    if not isinstance(value, int):
        raise StripeWebhookError("Stripe period end is malformed.")
    return datetime.fromtimestamp(value, UTC)


def _subscription_identifiers(
    *,
    event_object: dict[str, Any],
    subscription_data: dict[str, Any],
) -> tuple[str | None, str | None]:
    customer_id = event_object.get("customer") or subscription_data.get("customer")
    subscription_id = event_object.get("subscription") or subscription_data.get("id")
    return (
        str(customer_id) if customer_id else None,
        str(subscription_id) if subscription_id else None,
    )


def _resolve_tenant(
    db: Session,
    *,
    event_object: dict[str, Any],
    subscription_data: dict[str, Any],
) -> Tenant:
    metadata_tenant_id = _metadata_tenant_id(
        subscription_data.get("metadata") or event_object.get("metadata")
    )
    customer_id, subscription_id = _subscription_identifiers(
        event_object=event_object,
        subscription_data=subscription_data,
    )

    candidates = []
    if metadata_tenant_id is not None:
        candidates.append(db.scalar(select(Tenant).where(Tenant.id == metadata_tenant_id)))
    if customer_id is not None:
        candidates.append(
            db.scalar(
                select(Tenant)
                .join(Subscription, Subscription.tenant_id == Tenant.id)
                .where(Subscription.stripe_customer_id == customer_id)
            )
        )
    if subscription_id is not None:
        candidates.append(
            db.scalar(
                select(Tenant)
                .join(Subscription, Subscription.tenant_id == Tenant.id)
                .where(Subscription.stripe_subscription_id == subscription_id)
            )
        )

    tenants = {tenant.id: tenant for tenant in candidates if tenant is not None}
    if len(tenants) != 1:
        raise StripeWebhookError("Stripe event tenant identity is missing or inconsistent.")
    return next(iter(tenants.values()))


def _plan_for_subscription(
    db: Session,
    *,
    subscription_data: dict[str, Any],
    settings: Settings,
) -> Plan:
    price_id = _subscription_price_id(subscription_data)
    if price_id != settings.stripe_pro_price_id:
        raise StripeWebhookError("Stripe subscription price is not a configured plan.")
    plan = db.scalar(select(Plan).where(Plan.name == "Pro"))
    if plan is None:
        raise StripeWebhookError("The Pro plan is unavailable.")
    return plan


def _apply_subscription_state(
    *,
    subscription: Subscription,
    plan: Plan,
    subscription_data: dict[str, Any],
    event_created_at: datetime,
    event_id: str,
) -> None:
    customer_id = subscription_data.get("customer")
    subscription_id = subscription_data.get("id")
    status = subscription_data.get("status")
    if not isinstance(status, str) or not subscription_id:
        raise StripeWebhookError("Stripe subscription state is incomplete.")

    subscription.plan_id = plan.id
    subscription.status = status
    subscription.stripe_customer_id = str(customer_id) if customer_id else None
    subscription.stripe_subscription_id = str(subscription_id)
    subscription.current_period_end = _period_end(subscription_data)
    subscription.last_event_created_at = event_created_at
    subscription.last_event_id = event_id


def process_webhook_event(
    db: Session,
    *,
    event: dict[str, Any],
    adapter: StripeAdapter,
    settings: Settings,
) -> None:
    event_id = event.get("id")
    event_type = event.get("type")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        raise StripeWebhookError("Stripe event identity is malformed.")
    if event_type not in SUPPORTED_WEBHOOK_EVENTS:
        return

    event_created_at = _event_created_at(event)
    event_object = _event_object(event)

    existing_event = db.scalar(select(StripeEvent).where(StripeEvent.stripe_event_id == event_id))
    if existing_event is not None:
        db.commit()
        return

    with db.begin_nested():
        inserted = db.execute(
            pg_insert(StripeEvent)
            .values(
                stripe_event_id=event_id,
                event_type=event_type,
                stripe_created_at=event_created_at,
                payload=event,
            )
            .on_conflict_do_nothing(index_elements=["stripe_event_id"])
        )
        if inserted.rowcount == 0:
            db.commit()
            return

        if inserted.rowcount != 0:
            subscription_data = event_object
            if event_type == "checkout.session.completed":
                subscription_id = event_object.get("subscription")
                if not subscription_id:
                    raise StripeWebhookError("Checkout event has no subscription.")
                subscription_data = adapter.retrieve_subscription(
                    subscription_id=str(subscription_id)
                )

            tenant = _resolve_tenant(
                db,
                event_object=event_object,
                subscription_data=subscription_data,
            )
            subscription = db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant.id).with_for_update()
            )
            if subscription is None:
                raise StripeWebhookError("Tenant subscription is unavailable.")

            incoming_customer_id, incoming_subscription_id = _subscription_identifiers(
                event_object=event_object,
                subscription_data=subscription_data,
            )
            if (
                incoming_customer_id is not None
                and subscription.stripe_customer_id is not None
                and incoming_customer_id != subscription.stripe_customer_id
            ):
                raise StripeWebhookError("Stripe customer does not match the tenant subscription.")
            if (
                incoming_subscription_id is not None
                and subscription.stripe_subscription_id is not None
                and incoming_subscription_id != subscription.stripe_subscription_id
            ):
                raise StripeWebhookError(
                    "Stripe subscription does not match the tenant subscription."
                )

            if (
                subscription.last_event_created_at is not None
                and event_created_at <= subscription.last_event_created_at
            ):
                authoritative_data = subscription_data
                if incoming_subscription_id is not None:
                    authoritative_data = adapter.retrieve_subscription(
                        subscription_id=incoming_subscription_id
                    )
                plan = _plan_for_subscription(
                    db,
                    subscription_data=authoritative_data,
                    settings=settings,
                )
                authoritative_status = authoritative_data.get("status")
                if not isinstance(authoritative_status, str):
                    raise StripeWebhookError("Authoritative Stripe state is incomplete.")
                if authoritative_status != subscription.status:
                    subscription.plan_id = plan.id
                    subscription.status = authoritative_status
                    subscription.current_period_end = _period_end(authoritative_data)
            else:
                plan = _plan_for_subscription(
                    db,
                    subscription_data=subscription_data,
                    settings=settings,
                )
                if event_type == "customer.subscription.deleted":
                    subscription_data = {**subscription_data, "status": "canceled"}
                _apply_subscription_state(
                    subscription=subscription,
                    plan=plan,
                    subscription_data=subscription_data,
                    event_created_at=event_created_at,
                    event_id=event_id,
                )

        db.execute(
            StripeEvent.__table__.update()
            .where(StripeEvent.stripe_event_id == event_id)
            .values(processed_at=datetime.now(UTC))
        )

    db.commit()


def create_checkout_session(
    db: Session,
    *,
    tenant_id: UUID,
    request: CheckoutRequest,
    adapter: StripeAdapter,
    settings: Settings,
) -> CheckoutResponse:
    if request.plan_name != "Pro":
        raise HTTPException(status_code=400, detail="Only the Pro plan can be purchased.")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant not found.")

    subscription = db.scalar(
        select(Subscription).where(Subscription.tenant_id == tenant_id).with_for_update()
    )
    if subscription is None:
        raise HTTPException(status_code=402, detail="A subscription is required.")

    plan = db.scalar(select(Plan).where(Plan.name == request.plan_name))
    if plan is None:
        raise HTTPException(status_code=400, detail="The requested plan is unavailable.")

    if subscription.plan_id == plan.id and subscription.status in {"active", "trialing"}:
        raise HTTPException(status_code=409, detail="The tenant is already on the Pro plan.")

    if subscription.stripe_customer_id is None:
        customer_id = adapter.create_customer(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
        )
        subscription.stripe_customer_id = customer_id
    else:
        customer_id = subscription.stripe_customer_id
        adapter.update_customer_metadata(
            customer_id=customer_id,
            tenant_id=tenant.id,
        )

    session_id, checkout_url = adapter.create_checkout_session(
        customer_id=customer_id,
        price_id=settings.stripe_pro_price_id,
        tenant_id=tenant.id,
        plan_name=plan.name,
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
    )
    db.commit()
    return CheckoutResponse(session_id=session_id, checkout_url=checkout_url)
