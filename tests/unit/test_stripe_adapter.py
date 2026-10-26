from uuid import uuid4

from app.core.config import Settings
from app.integrations.stripe.client import StripeSDKAdapter


class FakeCustomerAPI:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def create(self, *, params: dict) -> object:
        self.created.append(params)
        return type("Customer", (), {"id": "cus_test"})()

    def update(self, customer_id: str, *, params: dict) -> None:
        self.updated.append((customer_id, params))


class FakeCheckoutSessionAPI:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, *, params: dict) -> object:
        self.created.append(params)
        return type(
            "CheckoutSession",
            (),
            {"id": "cs_test", "url": "https://checkout.test/session"},
        )()


class FakeStripeClient:
    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key
        self.customers = FakeCustomerAPI()
        self.checkout = type("Checkout", (), {})()
        self.checkout.sessions = FakeCheckoutSessionAPI()


def test_sdk_adapter_passes_checkout_metadata_and_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.stripe.client.stripe.StripeClient",
        FakeStripeClient,
    )
    settings = Settings(
        database_url="postgresql+psycopg://unused",
        stripe_secret_key="sk_test_secret",
        stripe_webhook_secret="whsec_secret",
        stripe_pro_price_id="price_pro",
        stripe_checkout_success_url="https://app.test/success",
        stripe_checkout_cancel_url="https://app.test/cancel",
    )
    adapter = StripeSDKAdapter(settings)
    tenant_id = uuid4()

    customer_id = adapter.create_customer(
        tenant_id=tenant_id,
        tenant_name="Example Tenant",
    )
    session_id, checkout_url = adapter.create_checkout_session(
        customer_id=customer_id,
        price_id="price_pro",
        tenant_id=tenant_id,
        plan_name="Pro",
        success_url=settings.stripe_checkout_success_url,
        cancel_url=settings.stripe_checkout_cancel_url,
    )

    assert adapter._client.secret_key == "sk_test_secret"
    assert adapter._client.customers.created == [
        {
            "name": "Example Tenant",
            "metadata": {"tenant_id": str(tenant_id)},
        }
    ]
    assert (session_id, checkout_url) == (
        "cs_test",
        "https://checkout.test/session",
    )
    assert adapter._client.checkout.sessions.created == [
        {
            "mode": "subscription",
            "customer": "cus_test",
            "line_items": [{"price": "price_pro", "quantity": 1}],
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
            "metadata": {"tenant_id": str(tenant_id), "plan_name": "Pro"},
            "subscription_data": {"metadata": {"tenant_id": str(tenant_id), "plan_name": "Pro"}},
        }
    ]
