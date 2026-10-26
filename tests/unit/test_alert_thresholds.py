from datetime import date
from uuid import uuid4

from app.services.alerts import enqueue_threshold_alerts


class FakeExecute:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement) -> None:
        self.statements.append(statement)


def test_threshold_enqueue_creates_both_quota_alerts() -> None:
    db = FakeExecute()

    enqueue_threshold_alerts(
        db,
        tenant_id=uuid4(),
        billing_month=date(2026, 10, 1),
        previous_api_calls=79,
        current_api_calls=80,
        api_call_limit=100,
        previous_ai_tokens=799,
        current_ai_tokens=800,
        ai_token_limit=1_000,
    )

    assert len(db.statements) == 2


def test_threshold_enqueue_ignores_non_crossings_and_zero_limits() -> None:
    db = FakeExecute()

    enqueue_threshold_alerts(
        db,
        tenant_id=uuid4(),
        billing_month=date(2026, 10, 1),
        previous_api_calls=80,
        current_api_calls=81,
        api_call_limit=100,
        previous_ai_tokens=0,
        current_ai_tokens=1,
        ai_token_limit=0,
    )

    assert db.statements == []
