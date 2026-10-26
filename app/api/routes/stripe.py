from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_db
from app.core.config import Settings, get_settings
from app.integrations.stripe.client import StripeAdapter, StripeSDKAdapter
from app.models.tenant import Tenant
from app.schemas.stripe import CheckoutRequest, CheckoutResponse
from app.services.stripe import (
    StripeWebhookError,
    create_checkout_session,
    process_webhook_event,
)

router = APIRouter(prefix="/stripe", tags=["stripe"])
webhook_router = APIRouter(tags=["stripe"])


def get_stripe_adapter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StripeAdapter:
    return StripeSDKAdapter(settings)


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    request: CheckoutRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    adapter: Annotated[StripeAdapter, Depends(get_stripe_adapter)],
) -> CheckoutResponse:
    return create_checkout_session(
        db,
        tenant_id=tenant.id,
        request=request,
        adapter=adapter,
        settings=settings,
    )


@webhook_router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    adapter: Annotated[StripeAdapter, Depends(get_stripe_adapter)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, str]:
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature.")

    payload = await request.body()
    try:
        event = adapter.construct_webhook_event(
            payload=payload,
            signature=stripe_signature,
            secret=settings.stripe_webhook_secret,
        )
        process_webhook_event(
            db,
            event=event,
            adapter=adapter,
            settings=settings,
        )
    except (ValueError, StripeWebhookError, stripe.error.StripeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook.") from exc

    return {"status": "ok"}
