from collections.abc import Generator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.stripe import get_stripe_adapter
from app.core.api_keys import generate_api_key, hash_api_key
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ApiKey, Plan, Subscription, Tenant


class FakeStripeAdapter:
    def __init__(self) -> None:
        self.created_customers: list[dict[str, str]] = []
        self.updated_customers: list[dict[str, str]] = []
        self.checkout_requests: list[dict[str, str]] = []

    def create_customer(self, *, tenant_id, tenant_name) -> str:
        self.created_customers.append({"tenant_id": str(tenant_id), "tenant_name": tenant_name})
        return "cus_created"

    def update_customer_metadata(self, *, customer_id, tenant_id) -> None:
        self.updated_customers.append({"customer_id": customer_id, "tenant_id": str(tenant_id)})

    def create_checkout_session(
        self,
        *,
        customer_id,
        price_id,
        tenant_id,
        plan_name,
        success_url,
        cancel_url,
    ) -> tuple[str, str]:
        self.checkout_requests.append(
            {
                "customer_id": customer_id,
                "price_id": price_id,
                "tenant_id": str(tenant_id),
                "plan_name": plan_name,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return "cs_test_123", "https://checkout.stripe.test/session"


def create_tenant(
    db_session: Session,
    *,
    stripe_customer_id: str | None = None,
) -> tuple[Tenant, str, Subscription]:
    raw_key = generate_api_key()
    free_plan = Plan(
        name=f"Free {uuid4()}",
        api_call_limit=1_000,
        ai_token_limit=100_000,
    )
    pro_plan = Plan(
        name="Pro",
        api_call_limit=100_000,
        ai_token_limit=10_000_000,
    )
    tenant = Tenant(name=f"Checkout Test Tenant {uuid4()}")
    db_session.add_all([free_plan, pro_plan, tenant])
    db_session.flush()

    db_session.add(
        ApiKey(
            tenant_id=tenant.id,
            key_hash=hash_api_key(raw_key),
            label="checkout-integration-test",
        )
    )
    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=free_plan.id,
        status="active",
        stripe_customer_id=stripe_customer_id,
    )
    db_session.add(subscription)
    db_session.flush()
    return tenant, raw_key, subscription


@contextmanager
def create_client(
    db_session: Session,
    adapter: FakeStripeAdapter,
) -> Generator[TestClient]:
    settings = Settings(
        database_url="postgresql+psycopg://unused",
        stripe_secret_key="sk_test_unused",
        stripe_webhook_secret="whsec_unused",
        stripe_pro_price_id="price_pro_test",
        stripe_checkout_success_url="https://app.test/success",
        stripe_checkout_cancel_url="https://app.test/cancel",
    )

    def override_get_db() -> Generator[Session]:
        yield db_session

    def override_get_settings() -> Settings:
        return settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_stripe_adapter] = lambda: adapter
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_stripe_adapter, None)


def test_checkout_creates_session_without_activating_paid_plan(
    db_session: Session,
) -> None:
    tenant, raw_key, subscription = create_tenant(db_session)
    adapter = FakeStripeAdapter()

    with create_client(db_session, adapter) as client:
        response = client.post(
            "/stripe/checkout",
            headers={"X-API-Key": raw_key},
            json={"plan_name": "Pro"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "cs_test_123",
        "checkout_url": "https://checkout.stripe.test/session",
    }
    assert adapter.created_customers == [{"tenant_id": str(tenant.id), "tenant_name": tenant.name}]
    assert adapter.checkout_requests == [
        {
            "customer_id": "cus_created",
            "price_id": "price_pro_test",
            "tenant_id": str(tenant.id),
            "plan_name": "Pro",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        }
    ]
    db_session.refresh(subscription)
    assert subscription.stripe_customer_id == "cus_created"
    assert subscription.status == "active"
    assert db_session.scalar(select(Plan).where(Plan.id == subscription.plan_id)).name.startswith(
        "Free"
    )


def test_checkout_reuses_customer_and_refreshes_metadata(
    db_session: Session,
) -> None:
    _, raw_key, _ = create_tenant(db_session, stripe_customer_id="cus_existing")
    adapter = FakeStripeAdapter()

    with create_client(db_session, adapter) as client:
        response = client.post(
            "/stripe/checkout",
            headers={"X-API-Key": raw_key},
            json={"plan_name": "Pro"},
        )

    assert response.status_code == 200
    assert adapter.created_customers == []
    assert adapter.updated_customers[0]["customer_id"] == "cus_existing"
    assert adapter.checkout_requests[0]["customer_id"] == "cus_existing"


def test_checkout_rejects_non_pro_target(db_session: Session) -> None:
    _, raw_key, _ = create_tenant(db_session)
    adapter = FakeStripeAdapter()

    with create_client(db_session, adapter) as client:
        response = client.post(
            "/stripe/checkout",
            headers={"X-API-Key": raw_key},
            json={"plan_name": "Free"},
        )

    assert response.status_code == 400
    assert adapter.created_customers == []
    assert adapter.checkout_requests == []


def test_checkout_requires_authenticated_tenant(db_session: Session) -> None:
    adapter = FakeStripeAdapter()

    with create_client(db_session, adapter) as client:
        response = client.post(
            "/stripe/checkout",
            json={"plan_name": "Pro"},
        )

    assert response.status_code == 401
    assert adapter.created_customers == []
