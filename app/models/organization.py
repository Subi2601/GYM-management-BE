"""Organization (SaaS tenant = a gym business) and its branches."""
from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Organization(BaseModel):
    __tablename__ = "org_organizations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    contact_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Branch(BaseModel):
    __tablename__ = "org_branches"
    __table_args__ = (
        UniqueConstraint("organization_id", "branch_name", name="uq_org_branches_org_name"),
        UniqueConstraint("checkin_token", name="uq_org_branches_checkin_token"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    branch_name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # QR attendance: the secret in the CHECK IN / OUT poster URLs (regenerate = old posters stop working),
    # and the gym's position — a scan counts only within `geofence_m` metres of it (no position = no check).
    checkin_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geofence_m: Mapped[int] = mapped_column(Integer, nullable=False, default=150, server_default=text("150"))
