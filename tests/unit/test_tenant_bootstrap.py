from collections.abc import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.api_keys import hash_api_key
from app.models import ApiKey, Base, Plan, Subscription, Tenant
from scripts import bootstrap_tenant, seed_plans


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    try:
        yield factory
    finally:
        engine.dispose()


def test_seed_plans_creates_expected_plans(
    session_factory: sessionmaker[Session],
) -> None:
    with patch.object(seed_plans, "get_session_factory", return_value=session_factory):
        seed_plans.seed_plans()

    with session_factory() as session:
        plans = {plan.name: plan for plan in session.scalars(select(Plan))}

    assert plans["Free"].api_call_limit == 1_000
    assert plans["Free"].ai_token_limit == 100_000
    assert plans["Pro"].api_call_limit == 100_000
    assert plans["Pro"].ai_token_limit == 10_000_000


def test_seed_plans_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    with patch.object(seed_plans, "get_session_factory", return_value=session_factory):
        seed_plans.seed_plans()
        seed_plans.seed_plans()

    with session_factory() as session:
        plans = list(session.scalars(select(Plan)))

    assert sorted(plan.name for plan in plans) == ["Free", "Pro"]


def test_seed_plans_rejects_unexpected_existing_limits(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(Plan(name="Free", api_call_limit=50, ai_token_limit=500))
        session.commit()

    with (
        patch.object(seed_plans, "get_session_factory", return_value=session_factory),
        pytest.raises(ValueError, match="different limits"),
    ):
        seed_plans.seed_plans()

    with session_factory() as session:
        free_plan = session.scalar(select(Plan).where(Plan.name == "Free"))

    assert free_plan is not None
    assert free_plan.api_call_limit == 50
    assert free_plan.ai_token_limit == 500


def test_bootstrap_stores_only_api_key_hash(
    session_factory: sessionmaker[Session],
) -> None:
    with patch.object(seed_plans, "get_session_factory", return_value=session_factory):
        seed_plans.seed_plans()

    with (
        patch.object(
            bootstrap_tenant,
            "get_session_factory",
            return_value=session_factory,
        ),
        patch.object(
            bootstrap_tenant,
            "generate_api_key",
            return_value="frk_test_secret_value",
        ),
    ):
        raw_key = bootstrap_tenant.create_tenant("Example Tenant")

    assert raw_key == "frk_test_secret_value"

    with session_factory() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.name == "Example Tenant"))
        key_record = session.scalar(select(ApiKey))
        subscription = session.scalar(select(Subscription))
        free_plan = session.scalar(select(Plan).where(Plan.name == "Free"))

        assert tenant is not None
        assert key_record is not None
        assert subscription is not None
        assert free_plan is not None

        assert key_record.tenant_id == tenant.id
        assert key_record.key_hash == hash_api_key(raw_key)
        assert key_record.key_hash != raw_key
        assert subscription.tenant_id == tenant.id
        assert subscription.plan_id == free_plan.id
        assert subscription.status == "active"


def test_bootstrap_fails_when_free_plan_is_missing(
    session_factory: sessionmaker[Session],
) -> None:
    with (
        patch.object(
            bootstrap_tenant,
            "get_session_factory",
            return_value=session_factory,
        ),
        pytest.raises(RuntimeError, match="Free plan is missing"),
    ):
        bootstrap_tenant.create_tenant("Example Tenant")

    with session_factory() as session:
        assert session.scalar(select(Tenant)) is None
        assert session.scalar(select(ApiKey)) is None
        assert session.scalar(select(Subscription)) is None


def test_bootstrap_rejects_empty_name_before_database_access() -> None:
    with (
        patch.object(
            bootstrap_tenant,
            "get_session_factory",
        ) as mock_factory,
        pytest.raises(ValueError, match="Tenant name must not be empty"),
    ):
        bootstrap_tenant.create_tenant("   ")

    mock_factory.assert_not_called()


def test_cli_displays_api_key_after_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_key = "frk_test_secret_value"

    monkeypatch.setattr(
        "sys.argv",
        ["bootstrap_tenant", "--name", "Example Tenant"],
    )

    with patch.object(
        bootstrap_tenant,
        "create_tenant",
        return_value=expected_key,
    ) as mock_create:
        exit_code = bootstrap_tenant.main()

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Tenant created successfully." in output
    assert "Copy this API key now; it will not be shown again:" in output
    assert expected_key in output
    mock_create.assert_called_once_with("Example Tenant")


def test_cli_does_not_display_api_key_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["bootstrap_tenant", "--name", "Example Tenant"],
    )

    with patch.object(
        bootstrap_tenant,
        "create_tenant",
        side_effect=RuntimeError("Bootstrap failed"),
    ):
        exit_code = bootstrap_tenant.main()

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "frk_" not in captured.out
    assert "Bootstrap failed" in captured.err
