# Stag Fitness Backend — Instructions

Multi-gym SaaS backend (FastAPI) for the Stag Fitness gym platform, migrated from Spring Boot.
Built on the TESS platform conventions (layering, `iam_core` / `rbac` / `shared` packages, auth, envelopes,
enum registry, soft delete, prefixed tables) **adapted for SaaS**: every business row carries
`organization_id` (tenant) + `branch_id`, and every query is scoped through `BranchScope`.

## Stack
Python 3.12 · FastAPI 0.111 · SQLAlchemy 2 async + asyncpg · Alembic 1.13 · Pydantic 2 · PostgreSQL 17 ·
PyJWT HS256 · bcrypt (cost 12) · cryptography (Fernet). No Redis / Celery / background jobs (not approved).

## Layering (strict)
`api/v1/<module>.py` (router: routes + `Depends(require_permission("x:y"))` only)
→ `controllers/` (build schemas, `ResponseEnvelope` / `PaginatedEnvelope`)
→ `services/` (all business logic, raises `shared.exceptions.http_exceptions`, one commit per command)
→ `repositories/` (SQLAlchemy only; branch data always through `BaseRepository.scoped()` / `get_scoped()`)
→ `models/`.

## Key rules
- **Scope**: routes take `scope: BranchScope = Depends(get_branch_scope)`. Header `X-Branch-ID`; missing =
  home branch, or "All Branches" (read-only) for accounts with `branch:switch`. Writes call
  `scope.require_branch()`.
- **Auth**: access token 4h (memory on the client), refresh token 1 day in httpOnly cookie
  `stag_refresh` (path `/api/v1/auth`), revocable `auth_sessions` with idle timeout.
- **RBAC**: permission codes live only in `app/utils/rbac_catalog.py` (seeded into `rbac_*` tables).
  Never branch on role names in code.
- **Secrets**: `JWT_SECRET` and `PII_KEY` live in `.env` (never committed). `PII_KEY` must not change
  once data exists — stored PII would become unreadable.
- **PII** (Aadhaar, PAN, ID-proof, bank account) stored Fernet-encrypted (`*_enc` columns); returned
  plain only with `pii:view`, otherwise masked `XXXX-XXXX-1234`. Never log PII or tokens.
- **Lists**: paginated lists take `search`, `sort_by` (a `Literal` whitelist mapped through
  `BaseRepository.ordered`) and `sort_dir`. A list with status tabs also exposes `GET /<list>/counts`
  (declared before `/{id}`): one query via `BaseRepository.count_tabs`, reusing the same per-tab condition
  function as the list so the numbers always match.
- **Enums** only in `app/core/enums.py`. **Dates**: business "today" = `app.core.timeutil.today()`
  (APP_TIMEZONE, default Asia/Kolkata). **Money**: `Numeric(12,2)` / Decimal in services, `float` in schemas.
- **Tables** are module-prefixed: `auth_`, `org_`, `member_`, `lead_`, `plan_`, `subscription_`, `payment_`,
  `pt_`, `staff_`, `attendance_`, `diet_`, `rbac_`. UUID PKs, UTC timestamps, soft delete (`soft_delete()`).
- **Attendance**: every visit (staff + members, several a day) is an `attendance_sessions` row (MANUAL or QR);
  staff also keep the `staff_attendance` day row (status, first in / last out) that payroll reads — both go through
  `AttendanceService.check_in / check_out`. **QR check-in** routes live under `/api/v1/public/checkin/{token}`
  (no login, AuthMiddleware skips `/api/v1/public/`): the branch comes from `org_branches.checkin_token`, the
  person from the `stag_device` cookie (phone linked once via phone + ID number, stored hashed in
  `attendance_devices`), optional geofence from the branch latitude / longitude. Public endpoints are rate limited
  in-process (`app/core/ratelimit.py`).

## Modules
auth · organizations (platform onboarding) · branches · members · leads · plans · subscriptions (enrol /
renew) · payments (stats, invoice) · personal training · employees · attendance · salary · food items ·
diet plans · dashboard. Endpoint list: `../docs/02_API_REFERENCE.md` (regenerate with
`python -m scripts.gen_api_reference`).

## Commands (PowerShell, from this folder)
```
python -m venv env; .\env\Scripts\pip install -r requirements.txt
.\env\Scripts\python -m scripts.gen_dev_secrets          # first time: prints JWT_SECRET / PII_KEY for .env
.\env\Scripts\alembic upgrade head
.\env\Scripts\python -m app.utils.seed                    # RBAC catalogue, demo org/branches/logins, foods, plans
.\env\Scripts\uvicorn app.main:app --port 8001 --reload   # 8001: the frontend proxy's default
.\env\Scripts\python -m scripts.smoke_test                # + smoke_org_plans_leads / smoke_billing / smoke_staff / smoke_diet / smoke_attendance
```
