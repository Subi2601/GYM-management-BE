"""Attendance sessions (every check-in → check-out, staff and members) and phones linked for QR check-in."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AttendancePersonType, AttendanceSource
from app.models.base import BaseModel, BranchScopedMixin

# Exactly one of employee_id / member_id is set, matching person_type.
_ONE_PERSON = ("(person_type = 'STAFF' AND employee_id IS NOT NULL AND member_id IS NULL) OR "
               "(person_type = 'MEMBER' AND member_id IS NOT NULL AND employee_id IS NULL)")


def _person_type():
    return mapped_column(Enum(AttendancePersonType, native_enum=False, create_constraint=False, length=10),
                         nullable=False)


def _source(nullable: bool):
    return mapped_column(Enum(AttendanceSource, native_enum=False, create_constraint=False, length=10),
                         nullable=nullable)


class AttendanceSession(BranchScopedMixin, BaseModel):
    """One visit: check-in and (once they leave) check-out. A person can have several per day.
    A refused QR check-in (e.g. expired membership) is kept as a row with `denied_reason` and no check-out."""
    __tablename__ = "attendance_sessions"
    __table_args__ = (CheckConstraint(_ONE_PERSON, name="ck_attendance_sessions_one_person"),)

    person_type: Mapped[AttendancePersonType] = _person_type()
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    check_in_time: Mapped[time] = mapped_column(Time, nullable=False)
    check_out_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    in_source: Mapped[AttendanceSource] = _source(nullable=False)
    out_source: Mapped[AttendanceSource | None] = _source(nullable=True)
    denied_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


class AttendanceDevice(BranchScopedMixin, BaseModel):
    """A phone linked to one person for QR check-in. The phone keeps a random token in a cookie; only its
    SHA-256 is stored. One phone per person: linking a new phone retires the old one."""
    __tablename__ = "attendance_devices"
    __table_args__ = (CheckConstraint(_ONE_PERSON, name="ck_attendance_devices_one_person"),)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    person_type: Mapped[AttendancePersonType] = _person_type()
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
