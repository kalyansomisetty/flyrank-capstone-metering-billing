from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant
from app.models.plan import Plan


def test_tenant_can_be_inserted_and_retrieved(db_session: Session) -> None:
    tenant = Tenant(name="Integration Test Tenant")
    db_session.add(tenant)
    db_session.flush()

    tenant_id = tenant.id
    db_session.expire_all()

    saved_tenant = db_session.scalars(select(Tenant).where(Tenant.id == tenant_id)).one()

    assert saved_tenant.name == "Integration Test Tenant"
    assert saved_tenant.id == tenant_id


def test_plan_can_be_inserted_and_retrieved(db_session: Session) -> None:
    plan = Plan(
        name="Integration Test Plan",
        api_call_limit=1000,
        ai_token_limit=100_000,
    )
    db_session.add(plan)
    db_session.flush()

    plan_id = plan.id
    db_session.expire_all()

    saved_plan = db_session.scalars(select(Plan).where(Plan.id == plan_id)).one()

    assert saved_plan.name == "Integration Test Plan"
    assert saved_plan.api_call_limit == 1000
    assert saved_plan.ai_token_limit == 100_000
