from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("name", name="uq_plans_name"),
        CheckConstraint("api_call_limit >= 0", name="ck_plans_api_call_limit_nonnegative"),
        CheckConstraint("ai_token_limit >= 0", name="ck_plans_ai_token_limit_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    api_call_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ai_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
