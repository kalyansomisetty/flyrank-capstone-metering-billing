from datetime import date
from uuid import uuid4

from app.models.alert import AlertOutbox
from app.services.alerts import (
    MAX_DELIVERY_ATTEMPTS,
    LoggingNotificationAdapter,
    PermanentDeliveryError,
    TransientDeliveryError,
    process_one_alert,
)


class FakeSession:
    def __init__(self, alert: AlertOutbox) -> None:
        self.alert = alert
        self.commits = 0

    def begin(self):
        return self

    def __enter__(self):
        self.commits += 1
        return self

    def __exit__(self, *_args):
        return False

    def scalar(self, *_args, **_kwargs):
        return self.alert

    def flush(self):
        return None


class FakeNotificationAdapter:
    def __init__(self, error=None) -> None:
        self.error = error
        self.calls = []

    def deliver(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.error:
            raise self.error


def make_alert() -> AlertOutbox:
    return AlertOutbox(
        id=uuid4(),
        tenant_id=uuid4(),
        billing_month=date(2026, 10, 1),
        usage_type="api_calls",
        threshold=80,
        payload={"usage_type": "api_calls"},
        status="pending",
        attempts=0,
    )


def test_worker_delivers_with_stable_notification_id() -> None:
    alert = make_alert()
    db = FakeSession(alert)
    adapter = FakeNotificationAdapter()

    assert process_one_alert(db, adapter) is True
    assert alert.status == "delivered"
    assert alert.delivered_at is not None
    assert adapter.calls[0]["notification_id"] == alert.id


def test_worker_retries_transient_failures_then_fails_boundedly() -> None:
    alert = make_alert()
    alert.attempts = MAX_DELIVERY_ATTEMPTS - 1
    db = FakeSession(alert)
    adapter = FakeNotificationAdapter(TransientDeliveryError("temporary"))

    assert process_one_alert(db, adapter) is True
    assert alert.status == "failed"
    assert alert.attempts == MAX_DELIVERY_ATTEMPTS


def test_worker_marks_permanent_failure_without_retry() -> None:
    alert = make_alert()
    db = FakeSession(alert)
    adapter = FakeNotificationAdapter(PermanentDeliveryError("permanent"))

    assert process_one_alert(db, adapter) is True
    assert alert.status == "failed"
    assert alert.attempts == 1


def test_logging_adapter_emits_delivery_without_payload(caplog) -> None:
    alert = make_alert()
    adapter = LoggingNotificationAdapter()

    with caplog.at_level("INFO"):
        adapter.deliver(
            notification_id=alert.id,
            tenant_id=alert.tenant_id,
            usage_type=alert.usage_type,
            payload={"sensitive": "not logged"},
        )

    assert "Usage threshold alert delivered" in caplog.text
    assert "not logged" not in caplog.text


def test_terminal_failure_emits_failure_alert(caplog) -> None:
    alert = make_alert()
    db = FakeSession(alert)
    adapter = FakeNotificationAdapter(PermanentDeliveryError("permanent"))

    with caplog.at_level("ERROR"):
        process_one_alert(db, adapter)

    assert "Usage threshold alert delivery permanently failed" in caplog.text
    failure_record = next(
        record
        for record in caplog.records
        if record.message == "Usage threshold alert delivery permanently failed"
    )
    assert failure_record.tenant_id == str(alert.tenant_id)
