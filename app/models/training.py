"""Personal training subscriptions and their logged sessions."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PTStatus
from app.models.base import BaseModel, BranchScopedMixin


class PTSubscription(BranchScopedMixin, BaseModel):
    __tablename__ = "pt_subscriptions"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_plans.id", ondelete="RESTRICT"), nullable=True,
    )
    # Set when created from a PERSONAL_TRAINING add-on subscription; paying that subscription pays this.
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    goal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    total_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    sessions_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[PTStatus] = mapped_column(
        Enum(PTStatus, name="pt_status"), nullable=False, default=PTStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )


class PTSessionLog(BranchScopedMixin, BaseModel):
    __tablename__ = "pt_session_logs"

    pt_subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pt_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="SET NULL"), nullable=True,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    trainer_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                   server_default=text("false"))
    client_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                  server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sessions_remaining_after: Mapped[int] = mapped_column(Integer, nullable=False)
