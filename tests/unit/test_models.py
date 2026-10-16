from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import Base

EXPECTED_TABLES = {
    "tenants",
    "api_keys",
    "plans",
    "subscriptions",
    "usage_events",
    "stripe_events",
    "quota_states",
    "alert_outbox",
}


def constraint_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def check_expressions(table_name: str) -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def server_default_expression(table_name: str, column_name: str) -> str:
    column = Base.metadata.tables[table_name].c[column_name]
    assert column.server_default is not None
    return " ".join(str(column.server_default.arg).split())


def test_all_models_are_registered_in_shared_metadata() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_key_uniqueness_constraints_are_declared() -> None:
    assert "uq_usage_events_tenant_idempotency_key" in constraint_names("usage_events")
    assert "uq_stripe_events_event_id" in constraint_names("stripe_events")
    assert "uq_quota_states_tenant_month" in constraint_names("quota_states")
    assert "uq_alert_outbox_identity" in constraint_names("alert_outbox")


def test_usage_event_constraints_require_a_billable_call() -> None:
    assert check_expressions("usage_events")["ck_usage_events_api_call_quantity_positive"] == (
        "api_call_quantity >= 1"
    )


def test_plan_limits_cannot_be_negative() -> None:
    expressions = check_expressions("plans")

    assert expressions["ck_plans_api_call_limit_nonnegative"] == "api_call_limit >= 0"
    assert expressions["ck_plans_ai_token_limit_nonnegative"] == "ai_token_limit >= 0"


def test_alert_threshold_and_attempt_constraints_are_declared() -> None:
    expressions = check_expressions("alert_outbox")

    assert expressions["ck_alert_outbox_attempts_nonnegative"] == "attempts >= 0"
    assert expressions["ck_alert_outbox_threshold_percent"] == "threshold BETWEEN 1 AND 100"


def test_server_defaults_match_intended_postgresql_expressions() -> None:
    expected_defaults = {
        ("usage_events", "api_call_quantity"): "1",
        ("usage_events", "cost_micro_units"): "0",
        ("quota_states", "api_calls_used"): "0",
        ("quota_states", "ai_tokens_used"): "0",
        ("quota_states", "cost_micro_units"): "0",
        ("alert_outbox", "status"): "pending",
        ("alert_outbox", "attempts"): "0",
    }

    for (table_name, column_name), expected in expected_defaults.items():
        assert server_default_expression(table_name, column_name) == expected
