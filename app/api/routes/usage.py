from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_db
from app.models.tenant import Tenant
from app.schemas.usage import UsageResponse
from app.services.usage import get_tenant_usage

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageResponse)
def get_usage(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[Session, Depends(get_db)],
) -> UsageResponse:
    """Return the authenticated tenant's current-month usage."""
    return get_tenant_usage(db, tenant_id=tenant.id)
