from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.stripe import get_stripe_adapter
from app.core.api_keys import generate_api_key, hash_api_key
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ApiKey, Plan, StripeEvent, Subscription, Tenant


class FakeWebhookAdapter:
    def __init__(self) -> None:
        self.event: dict = {}
        self.authoritative_subscription: dict | None = None
        self.construct_calls = 0
        self.retrieve_calls = 0

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
        secret: str,
    ) -> dict:
        self.construct_calls += 1
        if signature != "valid" or payload == b"malformed":
            raise ValueError("invalid signature")
        return self.event

    def retrieve_subscription(self, *, subscription_id: str) -> dict:
        self.retrieve_calls += 1
        if self.authoritative_subscription is None:
            raise AssertionError("authoritative subscription was not configured")
        return self.authoritative_subscription


def create_tenant(db_session: Session) -> tuple[Tenant, str, Subscription, Plan, Plan]:
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
    tenant = Tenant(name=f"Webhook Test Tenant {uuid4()}")
    db_session.add_all([free_plan, pro_plan, tenant])
    db_session.flush()
    db_session.add(
        ApiKey(
            tenant_id=tenant.id,
            key_hash=hash_api_key(raw_key),
            label="webhook-integration-test",
        )
    )
    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=free_plan.id,
        status="active",
        stripe_customer_id="cus_webhook",
    )
    db_session.add(subscription)
    db_session.flush()
    return tenant, raw_key, subscription, free_plan, pro_plan


def subscription_data(
    *,
    tenant_id: UUID,
    status: str = "active",
    subscription_id: str = "sub_webhook",
    current_period_end: int = 1_800_000_000,
) -> dict:
    return {
        "id": subscription_id,
        "customer": "cus_webhook",
        "status": status,
        "metadata": {"tenant_id": str(tenant_id)},
        "current_period_end": current_period_end,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_pro_test",
                    }
                }
            ]
        },
    }


def event(
    *,
    tenant_id: UUID,
    event_id: str,
    created: int,
    event_type: str = "customer.subscription.updated",
    status: str = "active",
) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "created": created,
        "data": {"object": subscription_data(tenant_id=tenant_id, status=status)},
    }


@contextmanager
def create_client(
    db_session: Session,
    adapter: FakeWebhookAdapter,
) -> Generator[TestClient]:
    settings = Settings(
        database_url="postgresql+psycopg://unused",
        stripe_secret_key="sk_test_unused",
        stripe_webhook_secret="whsec_test",
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


def post_webhook(
    client: TestClient,
    *,
    signature: str = "valid",
    payload: bytes = b'{"stripe":"payload"}',
):
    return client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": signature},
    )


def test_invalid_signature_does_not_mutate_database(db_session: Session) -> None:
    tenant, _, subscription, _, _ = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_invalid", created=100)

    with create_client(db_session, adapter) as client:
        response = post_webhook(client, signature="invalid")

    assert response.status_code == 400
    assert adapter.construct_calls == 1
    assert (
        db_session.scalar(select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_invalid"))
        is None
    )
    db_session.refresh(subscription)
    assert subscription.last_event_id is None


def test_malformed_payload_returns_400_without_mutation(db_session: Session) -> None:
    tenant, _, _, _, _ = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_malformed", created=150)

    with create_client(db_session, adapter) as client:
        response = post_webhook(client, payload=b"malformed")

    assert response.status_code == 400
    assert (
        db_session.scalar(select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_malformed"))
        is None
    )


def test_verified_upgrade_updates_usage_limits(db_session: Session) -> None:
    tenant, raw_key, subscription, free_plan, pro_plan = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_upgrade", created=200)

    with create_client(db_session, adapter) as client:
        response = post_webhook(client)
        usage_response = client.get("/usage", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    assert usage_response.status_code == 200
    assert usage_response.json()["plan_name"] == "Pro"
    assert usage_response.json()["api_call_limit"] == 100_000
    assert usage_response.json()["ai_token_limit"] == 10_000_000
    db_session.refresh(subscription)
    assert subscription.plan_id == pro_plan.id
    assert subscription.plan_id != free_plan.id
    assert subscription.status == "active"
    assert subscription.stripe_subscription_id == "sub_webhook"
    assert subscription.current_period_end == datetime.fromtimestamp(1_800_000_000, UTC)
    assert subscription.last_event_id == "evt_upgrade"
    assert (
        db_session.scalar(
            select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_upgrade")
        ).processed_at
        is not None
    )


def test_duplicate_event_is_safe_noop(db_session: Session) -> None:
    tenant, _, subscription, _, pro_plan = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_duplicate", created=300)

    with create_client(db_session, adapter) as client:
        first = post_webhook(client)
        second = post_webhook(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        db_session.scalar(
            select(func.count(StripeEvent.id)).where(StripeEvent.stripe_event_id == "evt_duplicate")
        )
        == 1
    )
    db_session.refresh(subscription)
    assert subscription.plan_id == pro_plan.id
    assert adapter.retrieve_calls == 0


def test_stale_event_reconciles_authoritative_state(db_session: Session) -> None:
    tenant, _, subscription, _, pro_plan = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_new", created=500)

    with create_client(db_session, adapter) as client:
        assert post_webhook(client).status_code == 200
        adapter.event = event(
            tenant_id=tenant.id,
            event_id="evt_old",
            created=400,
            status="canceled",
        )
        adapter.authoritative_subscription = subscription_data(
            tenant_id=tenant.id,
            status="active",
        )
        response = post_webhook(client)

    assert response.status_code == 200
    assert adapter.retrieve_calls == 1
    db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.plan_id == pro_plan.id
    assert subscription.last_event_id == "evt_new"


def test_deleted_subscription_is_not_billable(db_session: Session) -> None:
    tenant, raw_key, subscription, _, _ = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(
        tenant_id=tenant.id,
        event_id="evt_deleted",
        created=600,
        event_type="customer.subscription.deleted",
        status="active",
    )

    with create_client(db_session, adapter) as client:
        response = post_webhook(client)

        generation_response = client.post(
            "/generate",
            headers={"X-API-Key": raw_key, "Idempotency-Key": "after-delete"},
            json={
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 10,
                "reasoning_tokens": 0,
            },
        )

    assert response.status_code == 200
    assert generation_response.status_code == 402
    db_session.refresh(subscription)
    assert subscription.status == "canceled"


def test_invalid_subscription_state_rolls_back_event_and_subscription(
    db_session: Session,
) -> None:
    tenant, _, subscription, free_plan, _ = create_tenant(db_session)
    adapter = FakeWebhookAdapter()
    adapter.event = event(tenant_id=tenant.id, event_id="evt_rollback", created=700)
    adapter.event["data"]["object"]["items"]["data"][0]["price"]["id"] = "price_unknown"

    with create_client(db_session, adapter) as client:
        response = post_webhook(client)

    assert response.status_code == 400
    assert (
        db_session.scalar(select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_rollback"))
        is None
    )
    db_session.refresh(subscription)
    assert subscription.plan_id == free_plan.id
    assert subscription.last_event_id is None
