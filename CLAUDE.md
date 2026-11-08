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
- **Roles are per gym** (`rbac_roles.organization_id`, `level`): every organization has OWNER (100, always all
  permissions), SUB_ADMIN (80, all branches), MANAGER (50) and STAFF (10) — created by
  `RoleService.ensure_org_roles` (seed + new-gym onboarding; default grants only on first create) — plus its own roles
  at level 80 / 50 / 10. Rules in `RoleService`: `OWNER_ONLY` permissions (roles & access, add / delete branch) never
  go to another role; `branch:switch` only for level ≥ 80; nobody creates, edits or assigns a role at or above their
  own level. API `/api/v1/roles` (`role:list`, `role:manage`; `/roles/assignable` for `employee:login`). Staff logins
  take `role_id` (default Manager for admin / manager staff, else Staff); a job-title change doesn't change access.
  `auth_users.role` (AccountRole) is only a display field kept in step with the level (`account_kind`).
  After the roles migration run `python -m app.utils.seed` (moves old OWNER / ADMIN / TRAINER logins).
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
- **Offers** (`plan_offers`) are the discount master: billing sends `offer_id` and the backend applies the offer's %
  (`OfferService.discount_for`), refusing offers that are switched off or outside their dates. `category_ids` limits
  an offer to plan categories (empty = every plan); the % applies only to the matching lines.
- **Plans**: every plan belongs to an org-level category (`plan_categories`, owner-managed master under
  `/api/v1/plan-categories`; new orgs get `DEFAULT_CATEGORIES` in `PlanCategoryService.create_defaults`). Duration is
  `duration_months` (calendar months via `add_months`; `duration_days` = months × 30 for sorting only) or
  `duration_days`. Plans with members are made inactive (`is_active=false`), never deleted; the list has
  Active / Inactive tabs (`status=`, counts from `/plans/counts?category_id=&search=`) and a category filter. `group_size` / `free_members`
  = group packages: enrol sends `group_members` (existing `member_id` or new `name` + `phone`); each member gets a
  subscription with `price_share`. `id_check` needs `id_verified` on enrol. `all_branches` plans let the member
  check in at any branch of the org (visit recorded at that branch; `/attendance/members/visitors`).
  Load a tariff with `python -m scripts.load_stag_tariff --hide-old`.
- **Upgrades** (`SubscriptionService.upgrade`, POST `/subscriptions/upgrade`; options at
  GET `/subscriptions/member/{id}/upgrade`): only within `plan.upgrade_window_days` of the start (0 = never; default
  by duration via `default_upgrade_window`, also the model default), current plan not expired, fully paid, not a
  group package. Target must cost more and be at least as long (lower / shorter plans are listed with a `reason`).
  The new subscription starts on the old start date; the old one's cost (price − discount) is the credit
  (`upgrade_credit`), only the balance is billed (payment `amount` = price − credit). Links: old `upgraded_to_id`,
  new `upgraded_from_id`; the invoice shows `credit_amount` / `credit_label`. No downgrades.
- **Public enquiry form**: `org_branches.enquiry_token` (made on first `GET /api/v1/leads/enquiry-form`, regenerate
  with `POST …/regenerate`) → public `GET/POST /api/v1/public/enquiry/{token}` (`EnquiryService`): a submit creates a
  NEW lead (source ENQUIRY_FORM, follow-up today, `created_by` NULL) or, for a phone with an open lead in the branch,
  appends a note and brings it back to today's follow-ups. Rate limited per IP and per phone; `website` is a honeypot.
  The enquiry router is registered before the leads router (`/leads/enquiry-form` is not a lead id).
- **Gym profile** (Gym Settings page; `GymProfileService`, `/api/v1/gym-profile`, read by any login, change
  `gym:manage`): name, tagline, contact email / phone, address, GSTIN, invoice footer on `org_organizations`; logo
  and terms & conditions PDF in `org_files` (one per kind, bytea), served publicly at
  `/api/v1/public/gyms/{code}/logo|terms` (versioned links via `file_url`). Branches carry their own `phone` /
  `email` (not unique) / `gstin` override and one `is_head_office` (can't be deleted). The invoice letterhead uses
  branch contacts else the gym's (never hard-code a letterhead); `/auth/me` returns `organization_logo_url`.
- **Configuration** (formerly "Gym settings"; columns on `org_organizations`, gym-wide): `trial_enabled / trial_days / trial_fee`,
  `renewal_due_days` (Members "Expiring" + Renewals default window), `renewal_overdue_days` (lapsed kept on Renewals),
  `late_grace_minutes` (staff late marking). Services read them via `SettingsService.values(org_id)` — never
  hard-code these windows. API `GET/PUT /api/v1/settings` (`setting:manage`), read-only `GET /settings/desk` for every
  login. Existing gyms' Sub-admin roles don't get `setting:manage` automatically (grants seed only on first create).
- **Trial class** (on the lead, one per lead): `POST /leads/{id}/trial` {start_date} books `trial_days` from the start
  (fee snapshot, follow-up on the last day), `DELETE …/trial` only with no visits / payment, `…/trial/visit` once a day
  inside the dates (paid trials need the fee first), `…/trial/paid` {payment_mode} records the fee on the lead (not a
  Payment / receipt — those need a member). The public enquiry form books it with `trial` + `trial_date`
  (today … +14 days); a phone that already had a trial gets `trial_used`. Leads tab `trial` = booked and still open.
- **Staff late / half day** (`attendance_service.day_status`): the day's first check-in after shift start +
  `late_grace_minutes` = LATE, at or after `half_day_after_minutes` = HALF_DAY (0 = never). Payroll cuts half a
  day's pay per HALF_DAY (`compute_salary`).
- **Membership actions** (`MembershipService`, `/api/v1/memberships`, every write needs `membership:manage` — manager
  level): act on the membership running today (`actionable_membership`). "Days used" = start → today minus frozen
  days. **Freeze**: total days = the subscription's `freeze_allowance_days` (member's own) else the gym's
  `freeze_max_days` (0 = only members given their own days), at most `freeze_max_times`, one running at a time;
  days are added to `end_date` at once (queued renewals shift), resume early gives unused days back; check-in is
  refused while frozen; upgrades carry `frozen_days`. **Transfer**: once (`transferred_from_id` set = can't move
  again), plain single memberships, fully paid, days used ≤ `transfer_within_days`; receiver gets a new row from today
  to the old end (paid by the giver: `payment_status` PAID). **Cancel**: always; refund only on `plan.refundable`
  within `plan.refund_window_days` (else gym `refund_within_days`), up to what was paid, suggested = paid − gym
  `refund_deduction_percent` → `payment_refunds` (RF-0001, bank account Fernet). Closed rows keep `closed_reason`
  (CANCELLED / TRANSFERRED), `closed_on`, `close_note`, end_date = the day before; renewals skip them. Every action
  needs a reason; proof files go in `member_documents` (bytea, ≤ 5 MB, base64 in JSON). Payment stats / dashboard
  revenue subtract refunds. New permissions reach existing built-in roles via `RoleService._roll_out_new` on seed
  (only permissions the owner never ticked / unticked).
- **Referrals** (`ReferralService`, `/api/v1/referrals`; view `referral:list`, set reward / give `referral:manage`):
  `member.referred_by_id` (set on the member form, or from a REFERRAL lead's `referred_by_id` on conversion; loop and
  self checks via `MemberRepository.referrer_chain`). A referral counts in the month the referred member joined, once
  they have a paid subscription. Each month has its own reward (`referral_programs` + `referral_tiers`, gym-wide,
  "refer ≥ N → reward", highest reached wins); it only works in its month (no reward set = desk can't give, "contact
  admin"). Ended months are settled once (`_settle`, lazily on the first read): every referrer who reached a tier
  gets a PENDING `referral_rewards` row (with `referral_reward_members` = the referrals it was for); `/give` marks it
  GIVEN, or gives this month's directly. Rewards count **direct referrals only** (A→B→C: C counts for B, not A).
  `/referrals/tree/{member}` returns direct referrals by default (`levels=1`; up to 8 for the kept-aside network chart)
  with plan, `paid`, `counted_status` and the member's rewards.
- **Offers** can give any mix of % off, extra months / days (added to covered membership end dates by
  `OfferService.apply_bonus`) and a free item; the bonus text is stored on `payment.offer_bonus` and printed.
- **Members "Not coming"** tab (`filter=absent`): running membership, no check-in for `absent_alert_days` (counted from
  the start for people who never came), not frozen today; list rows carry `last_visit_date`.
- **Gym ID** = `org_organizations.code` (in `/auth/me` as `organization_code`, invoices, settings). Member ids are
  `<member_id_prefix or code>-###` (existing gyms keep `SG`).
- **Client assessments** (`/api/v1/assessments`, view `member:list`, write `member:update`): vitals, lifestyle,
  injuries / surgeries, posture notes, movement ratings (`movements` JSONB); the newest updates the member's
  height / weight.
- **Shared invoice link**: `InvoiceResponse.share_token` (HMAC, `app/core/share_token.py`) → public
  `GET /api/v1/public/invoice/{token}`; the desk sends `/i/<token>` on WhatsApp (click-to-chat, no WhatsApp API).
- **Renewals**: latest membership per member ending within N days / lapsed ≤ 30 days; reminders are stamped on the
  subscription (`reminded_at`, `reminder_count`).
- **Staff logins**: `auth_users.employee_id` links an account to an employee, homed in the employee's branch
  (`StaffLoginService`, permission `employee:login`); terminating the employee disables the login.

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
.\env\Scripts\python -m scripts.smoke_test                # + smoke_org_plans_leads / smoke_billing / smoke_staff / smoke_diet / smoke_attendance / smoke_members_extras / smoke_plans_groups / smoke_upgrade / smoke_roles / smoke_enquiry / smoke_trial_settings / smoke_memberships / smoke_referrals / smoke_gym_profile (pass http://127.0.0.1:8001 as the base URL)
```
