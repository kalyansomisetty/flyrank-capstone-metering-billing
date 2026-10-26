"""HTTP route for billable generation requests."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_db
from app.models.tenant import Tenant
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services.generation import process_generation_request

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse)
def generate(
    request: GenerateRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key"),
    ],
) -> GenerateResponse:
    """Record usage and return the simulated generation result."""
    return process_generation_request(
        db,
        tenant_id=tenant.id,
        request=request,
        idempotency_key=idempotency_key,
    )
