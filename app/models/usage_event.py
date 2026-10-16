from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class UsageEvent(TimestampMixin, Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_usage_events_tenant_idempotency_key"
        ),
        Index("ix_usage_events_tenant_billing_month", "tenant_id", "billing_month"),
        CheckConstraint(
            "api_call_quantity >= 1", name="ck_usage_events_api_call_quantity_positive"
        ),
        CheckConstraint("input_tokens >= 0", name="ck_usage_events_input_tokens_nonnegative"),
        CheckConstraint(
            "cached_input_tokens >= 0", name="ck_usage_events_cached_input_nonnegative"
        ),
        CheckConstraint(
            "cached_input_tokens <= input_tokens", name="ck_usage_events_cached_input_lte_input"
        ),
        CheckConstraint("output_tokens >= 0", name="ck_usage_events_output_tokens_nonnegative"),
        CheckConstraint("reasoning_tokens >= 0", name="ck_usage_events_reasoning_nonnegative"),
        CheckConstraint(
            "reasoning_tokens <= output_tokens", name="ck_usage_events_reasoning_lte_output"
        ),
        CheckConstraint("cost_micro_units >= 0", name="ck_usage_events_cost_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    billing_month: Mapped[date] = mapped_column(Date, nullable=False)
    api_call_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    cost_micro_units: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
