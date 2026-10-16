from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class AlertOutbox(TimestampMixin, Base):
    __tablename__ = "alert_outbox"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "billing_month",
            "usage_type",
            "threshold",
            name="uq_alert_outbox_identity",
        ),
        CheckConstraint("attempts >= 0", name="ck_alert_outbox_attempts_nonnegative"),
        CheckConstraint("threshold BETWEEN 1 AND 100", name="ck_alert_outbox_threshold_percent"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    billing_month: Mapped[date] = mapped_column(Date, nullable=False)
    usage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1024))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
