"""QR attendance — the branch posters (token + gym location), linked phones and the public scan flow.

A poster URL carries the branch's random `checkin_token`. The first scan on a phone asks for the phone number +
ID number; that links the phone to the person (a random device token in an httpOnly cookie, stored hashed).
Later scans check the gym location and run the same check-in / check-out as the front desk.
"""
from __future__ import annotations

import hashlib
import math
import re
import secrets
from uuid import UUID

from fastapi import HTTPException, status
from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import AttendancePersonType, AttendanceSource
from app.core.ratelimit import SlidingWindowLimiter
from app.core.scope import BranchScope
from app.models.attendance import AttendanceDevice
from app.models.base import utcnow
from app.models.organization import Branch, Organization
from app.repositories.attendance_session_repository import AttendanceSessionRepository
from app.services.attendance_service import AttendanceService, Person

# Wrong ID numbers per phone number, and verify attempts per network address, within 15 minutes.
_FAILED_ID = SlidingWindowLimiter(limit=5, window_seconds=15 * 60)
_VERIFY_PER_IP = SlidingWindowLimiter(limit=30, window_seconds=15 * 60)
# GPS error tolerated on top of the branch radius (phones often report 20–60 m indoors).
_MAX_ACCURACY_ALLOWANCE_M = 100


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _id_number(code: str) -> int | None:
    """SG-EMP-029 → 29, SG-001 → 1 (what the person types: "29", "029" or the full code)."""
    digits = _digits(code)
    return int(digits) if digits else None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine), metres."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _too_many(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=message)


class CheckinService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = AttendanceSessionRepository(db)
        self._attendance = AttendanceService(db)

    # ── public: scan flow ────────────────────────────────────────────────
    async def _branch(self, token: str) -> Branch:
        branch = await self._repo.branch_by_token(token) if token else None
        if branch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="This QR code is no longer valid. Ask the front desk for the current one")
        return branch

    @staticmethod
    def _scope(branch: Branch) -> BranchScope:
        return BranchScope(branch.organization_id, branch.id, (branch.id,))

    async def _linked_person(self, branch: Branch, device_token: str | None) -> tuple[AttendanceDevice, Person] | None:
        """The person this phone is linked to, if they may check in at this branch (None = verify first).
        Staff: their own branch only. Members: their home branch, or any branch while on an all-branches plan —
        one phone link works everywhere they are allowed."""
        if not device_token:
            return None
        device = await self._repo.device_by_hash(_hash(device_token))
        if device is None or device.organization_id != branch.organization_id:
            return None
        scope = self._scope(branch)
        if device.person_type == AttendancePersonType.STAFF:
            if device.branch_id != branch.id:
                return None
            employee = await self._repo.get_employee(device.employee_id, scope)  # type: ignore[arg-type]
            return (device, Person.staff(employee)) if employee else None
        member = await self._repo.get_member(device.member_id, scope)  # type: ignore[arg-type]
        if member is None:
            member = await self._repo.visitor(branch.organization_id, device.member_id, timeutil.today())
        return (device, Person.of_member(member)) if member else None

    async def info(self, token: str, device_token: str | None) -> dict:
        branch = await self._branch(token)
        org = await self._db.get(Organization, branch.organization_id)
        linked = await self._linked_person(branch, device_token)
        return {"branch_name": branch.branch_name, "organization_name": org.name if org else "",
                "location_required": branch.latitude is not None and branch.longitude is not None,
                "person": {"name": linked[1].name, "person_type": linked[1].type} if linked else None}

    async def verify(self, token: str, body, device_token: str | None, ip: str,
                     user_agent: str | None) -> tuple[dict, str]:
        """Links this phone to the person with that phone number + ID number. Returns (person, new device token)."""
        branch = await self._branch(token)
        if _VERIFY_PER_IP.blocked(ip):
            raise _too_many("Too many attempts from this network. Try again in 15 minutes")
        _VERIFY_PER_IP.hit(ip)
        phone = _digits(body.phone)[-10:]
        limit_key = f"{branch.id}:{phone}"
        if _FAILED_ID.blocked(limit_key):
            raise _too_many("Too many wrong attempts for this phone number. Try again in 15 minutes")

        typed = _id_number(body.id_number)
        employee = await self._repo.staff_by_phone(branch.id, phone)
        member = await self._repo.member_by_phone(branch.id, phone)
        if member is None:   # visiting from another branch on an all-branches plan
            member = await self._repo.visitor_by_phone(branch.organization_id, phone, timeutil.today())
        # The same number can belong to a staff member and a member — the ID number decides.
        person: Person | None = None
        if employee is not None and typed is not None and _id_number(employee.employee_code) == typed:
            person = Person.staff(employee)
        elif member is not None and typed is not None and _id_number(member.registration_id) == typed:
            person = Person.of_member(member)
        if person is None:
            _FAILED_ID.hit(limit_key)
            raise BadRequestError("Phone number and ID number don't match our records. Check them or ask the front desk")
        _FAILED_ID.reset(limit_key)

        # One phone = one person: a phone already linked to someone else here can't be re-linked from the phone.
        current = await self._linked_person(branch, device_token)
        if current is not None and current[1].id != person.id:
            raise BadRequestError("This phone is already linked to another person. Ask the front desk to unlink it")
        # One person = one phone: linking this phone retires any other phone of theirs.
        for old in await self._repo.devices_of(person.type, person.id, None):
            old.soft_delete()
        new_token = secrets.token_urlsafe(32)
        await self._repo.add(AttendanceDevice(
            organization_id=branch.organization_id, branch_id=branch.id, token_hash=_hash(new_token),
            person_type=person.type, employee_id=person.employee.id if person.employee else None,
            member_id=person.member.id if person.member else None,
            user_agent=(user_agent or "")[:200] or None, last_used_at=utcnow()))
        await self._repo.commit()
        return {"name": person.name, "person_type": person.type}, new_token

    async def scan(self, token: str, body, device_token: str | None) -> dict:
        branch = await self._branch(token)
        linked = await self._linked_person(branch, device_token)
        if linked is None:
            raise BadRequestError("This phone isn't linked yet. Verify your phone number to continue")
        device, person = linked
        self._check_location(branch, body.latitude, body.longitude, body.accuracy)
        device.last_used_at = utcnow()
        scope = self._scope(branch)
        if body.direction == "in":
            return await self._attendance.check_in(person, scope, AttendanceSource.QR, None)
        return await self._attendance.check_out(person, scope, AttendanceSource.QR, None)

    @staticmethod
    def _check_location(branch: Branch, lat: float | None, lon: float | None, accuracy: float | None) -> None:
        if branch.latitude is None or branch.longitude is None:
            return   # the gym's location isn't set — the QR alone is enough
        if lat is None or lon is None:
            raise BadRequestError("Turn on location for this page to check in")
        away = distance_m(branch.latitude, branch.longitude, lat, lon)
        allowance = min(max(accuracy or 0, 0), _MAX_ACCURACY_ALLOWANCE_M)
        if away > branch.geofence_m + allowance:
            raise BadRequestError(f"You're about {round(away):,} m from {branch.branch_name}. "
                                  "Scan the QR inside the gym")

    # ── admin: posters, location, linked phones ──────────────────────────
    async def _admin_branch(self, scope: BranchScope) -> Branch:
        branch = await self._repo.get_branch(scope.require_branch(), scope.organization_id)
        if branch is None:
            raise NotFoundError("Branch")
        return branch

    @staticmethod
    def qr_out(branch: Branch) -> dict:
        return {"branch_id": branch.id, "branch_name": branch.branch_name, "checkin_token": branch.checkin_token,
                "latitude": branch.latitude, "longitude": branch.longitude, "geofence_m": branch.geofence_m}

    async def qr_settings(self, scope: BranchScope, actor: RequestContext) -> dict:
        branch = await self._admin_branch(scope)
        if branch.checkin_token is None:   # first visit to the QR screen creates the posters
            await self._repo.set_token_if_missing(branch, secrets.token_urlsafe(24))
        return self.qr_out(branch)

    async def regenerate(self, scope: BranchScope, actor: RequestContext) -> dict:
        branch = await self._admin_branch(scope)
        branch.checkin_token = secrets.token_urlsafe(24)
        branch.updated_by = actor.user_id
        await self._repo.commit()
        return self.qr_out(branch)

    async def update_location(self, body, scope: BranchScope, actor: RequestContext) -> dict:
        if (body.latitude is None) != (body.longitude is None):
            raise BadRequestError("Enter both latitude and longitude, or clear both")
        branch = await self._admin_branch(scope)
        branch.latitude, branch.longitude, branch.geofence_m = body.latitude, body.longitude, body.geofence_m
        branch.updated_by = actor.user_id
        await self._repo.commit()
        return self.qr_out(branch)

    async def devices(self, scope: BranchScope) -> list[dict]:
        out = []
        for device, staff_name, staff_code, member_name, member_reg in await self._repo.list_devices(scope):
            staff = device.person_type == AttendancePersonType.STAFF
            out.append({"id": device.id, "person_type": device.person_type,
                        "person_name": staff_name if staff else member_name,
                        "person_code": staff_code if staff else member_reg,
                        "user_agent": device.user_agent, "last_used_at": device.last_used_at,
                        "created_at": device.created_at})
        return out

    async def unlink(self, device_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        scope.require_branch()
        device = await self._repo.get_device(device_id, scope)
        if device is None:
            raise NotFoundError("Linked phone")
        device.soft_delete(actor.user_id)
        await self._repo.commit()
