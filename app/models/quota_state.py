from datetime import date
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class QuotaState(TimestampMixin, Base):
    __tablename__ = "quota_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "billing_month", name="uq_quota_states_tenant_month"),
        CheckConstraint("api_calls_used >= 0", name="ck_quota_states_api_calls_nonnegative"),
        CheckConstraint("ai_tokens_used >= 0", name="ck_quota_states_ai_tokens_nonnegative"),
        CheckConstraint("cost_micro_units >= 0", name="ck_quota_states_cost_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    billing_month: Mapped[date] = mapped_column(Date, nullable=False)
    api_calls_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    ai_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cost_micro_units: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
