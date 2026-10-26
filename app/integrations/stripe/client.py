from typing import Any, Protocol
from uuid import UUID

import stripe
from app.core.config import Settings


class StripeAdapter(Protocol):
    def create_customer(self, *, tenant_id: UUID, tenant_name: str) -> str: ...

    def update_customer_metadata(self, *, customer_id: str, tenant_id: UUID) -> None: ...

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        tenant_id: UUID,
        plan_name: str,
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]: ...

    def construct_webhook_event(
        self, *, payload: bytes, signature: str, secret: str
    ) -> dict[str, Any]: ...

    def retrieve_subscription(self, *, subscription_id: str) -> dict[str, Any]: ...


class StripeSDKAdapter:
    def __init__(self, settings: Settings) -> None:
        self._client = stripe.StripeClient(settings.stripe_secret_key)

    def create_customer(self, *, tenant_id: UUID, tenant_name: str) -> str:
        customer = self._client.customers.create(
            params={
                "name": tenant_name,
                "metadata": {"tenant_id": str(tenant_id)},
            }
        )
        return customer.id

    def update_customer_metadata(self, *, customer_id: str, tenant_id: UUID) -> None:
        self._client.customers.update(
            customer_id,
            params={"metadata": {"tenant_id": str(tenant_id)}},
        )

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        tenant_id: UUID,
        plan_name: str,
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        session = self._client.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "plan_name": plan_name,
                },
                "subscription_data": {
                    "metadata": {
                        "tenant_id": str(tenant_id),
                        "plan_name": plan_name,
                    }
                },
            }
        )
        if not session.url:
            raise RuntimeError("Stripe Checkout did not return a session URL.")
        return session.id, session.url

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
        secret: str,
    ) -> dict[str, Any]:
        event = stripe.Webhook.construct_event(payload, signature, secret)
        return event.to_dict_recursive()

    def retrieve_subscription(self, *, subscription_id: str) -> dict[str, Any]:
        subscription = self._client.v1.subscriptions.retrieve(subscription_id)
        return subscription.to_dict_recursive()
