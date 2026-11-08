"""Organization (SaaS tenant = a gym business) and its branches."""
from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import (Boolean, Float, ForeignKey, Integer, LargeBinary, Numeric, SmallInteger, String,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Organization(BaseModel):
    __tablename__ = "org_organizations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    contact_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)   # one or more numbers
    # ── Gym profile (Gym Settings page): letterhead on invoices, enquiry form, sidebar ──
    tagline: Mapped[str | None] = mapped_column(String(120), nullable=True)        # "Lifestyle & fitness studio"
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)        # registered / head office
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)           # a branch may override it
    invoice_footer: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Gym settings (owner-editable, every branch; SettingsService) ──
    # Trial class: offered on the enquiry form and from Leads; `trial_fee` 0 = free.
    trial_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    trial_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3, server_default=text("3"))
    trial_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default=text("0"))
    # Renewals: "expiring" = ends within `renewal_due_days`; lapsed memberships stay on the Renewals list
    # for `renewal_overdue_days`.
    renewal_due_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7, server_default=text("7"))
    renewal_overdue_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30,
                                                      server_default=text("30"))
    # Staff are late when the day's first check-in is more than this after their shift starts.
    late_grace_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10,
                                                    server_default=text("10"))
    # ...and the day counts as a half day (half a day's pay) when they come this late. 0 = never.
    half_day_after_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30,
                                                        server_default=text("30"))
    # Members with an active membership but no visit for this many days show on Members → "Not coming".
    absent_alert_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7, server_default=text("7"))
    # Member registration ids: <prefix>-001. NULL = the gym code.
    member_id_prefix: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Membership freeze: total days and number of freezes per membership (a member's own allowance overrides
    # the days; 0 days = only members given their own allowance can freeze).
    freeze_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    freeze_max_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30, server_default=text("30"))
    freeze_max_times: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2, server_default=text("2"))
    # Transfer to another person: once per membership, while it has been used for at most this many days.
    transfer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    transfer_within_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30,
                                                      server_default=text("30"))
    # Refund on cancel (plans marked refundable): within these days of use, minus this % of what was paid.
    refund_within_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7, server_default=text("7"))
    refund_deduction_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=10,
                                                              server_default=text("10"))


class Branch(BaseModel):
    __tablename__ = "org_branches"
    __table_args__ = (
        UniqueConstraint("organization_id", "branch_name", name="uq_org_branches_org_name"),
        UniqueConstraint("checkin_token", name="uq_org_branches_checkin_token"),
        UniqueConstraint("enquiry_token", name="uq_org_branches_enquiry_token"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    branch_name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Branch contacts (empty = the gym's); not unique — the head office often shares the gym's number.
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)          # e.g. a branch in another state
    is_head_office: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # QR attendance: the secret in the CHECK IN / OUT poster URLs (regenerate = old posters stop working),
    # and the gym's position — a scan counts only within `geofence_m` metres of it (no position = no check).
    checkin_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Public enquiry form: the secret in the /enquiry/<token> link + QR (regenerate = old links stop working).
    enquiry_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geofence_m: Mapped[int] = mapped_column(Integer, nullable=False, default=150, server_default=text("150"))


class OrgFile(BaseModel):
    """A gym-wide file set on the Gym Settings page: LOGO (image) or TERMS (terms & conditions PDF). One of each
    per gym; served publicly by gym code (shared on invoices / WhatsApp)."""
    __tablename__ = "org_files"
    __table_args__ = (UniqueConstraint("organization_id", "kind", name="uq_org_files_org_kind"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
