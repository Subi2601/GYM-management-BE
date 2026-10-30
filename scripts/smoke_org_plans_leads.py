"""API smoke test — organizations, branches, plans, leads — against a running server.

    python -m scripts.smoke_org_plans_leads [base_url]

Re-runnable: every name / email / phone / code carries a per-run suffix.
The "plan in use" checks insert one subscription + one PT subscription directly in the DB
(the subscription / PT endpoints belong to other modules), so .env must point at the server's DB.
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
RUN = f"{int(time.time()) % 10_000_000:07d}"
failures = 0


def check(label: str, resp: httpx.Response, expect: int = 200) -> dict:
    global failures
    ok = resp.status_code == expect
    if not ok:
        failures += 1
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    print(f"{'PASS' if ok else 'FAIL'} {label}: {resp.status_code} {'' if ok else body}")
    return body


def expect(label: str, condition: bool, detail: object = "") -> None:
    global failures
    if not condition:
        failures += 1
    print(f"{'PASS' if condition else 'FAIL'} {label} {'' if condition else detail}")


def phone(n: int) -> str:
    return f"7{RUN}{n:02d}"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30)


def login(c: httpx.Client, email: str, password: str, expect_status: int = 200) -> None:
    body = check(f"login {email}", c.post("/api/v1/auth/login", json={"email": email, "password": password}),
                 expect_status)
    if expect_status == 200:
        c.headers["Authorization"] = f"Bearer {body['data']['access_token']}"


# ── direct DB helper: make a plan "in use" ────────────────────────────────
async def _attach_usage(org_id: str, branch_id: str, member_id: str, plan_id: str, pt_plan_id: str) -> None:
    from uuid import UUID

    from app.database import AsyncSessionLocal, engine
    from app.models.billing import Subscription
    from app.models.training import PTSubscription

    today = date.today()
    async with AsyncSessionLocal() as db:
        db.add(Subscription(organization_id=UUID(org_id), branch_id=UUID(branch_id), member_id=UUID(member_id),
                            plan_id=UUID(plan_id), start_date=today, end_date=today + timedelta(days=30)))
        db.add(PTSubscription(organization_id=UUID(org_id), branch_id=UUID(branch_id), member_id=UUID(member_id),
                              plan_id=UUID(pt_plan_id), total_sessions=12, sessions_remaining=12,
                              start_date=today, expiry_date=today + timedelta(days=30)))
        await db.commit()
    await engine.dispose()   # each asyncio.run() has its own loop — never reuse pooled connections


# ── direct DB helper: throw-away superadmin ───────────────────────────────
# The seeded superadmin@stag.local cannot sign in: LoginRequest.email is EmailStr and email-validator
# rejects the special-use ".local" TLD. Until auth is fixed, a temporary superadmin with a normal domain
# is created for the run and disabled afterwards.
TEMP_SA_EMAIL, TEMP_SA_PASSWORD = f"sa{RUN}@stagsmoke.in", f"Sa-{RUN}-pw"


async def _temp_superadmin(enable: bool) -> None:
    from sqlalchemy import select

    from app.core.enums import AccountRole
    from app.core.security import hash_password
    from app.database import AsyncSessionLocal, engine
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        if enable:
            db.add(User(email=TEMP_SA_EMAIL, name="Smoke Superadmin", password_hash=hash_password(TEMP_SA_PASSWORD),
                        role=AccountRole.OWNER, is_superadmin=True))
        else:   # disable this run's account and any left over by an interrupted run
            stmt = select(User).where(User.email.like("sa%@stagsmoke.in"), User.is_superadmin.is_(True),
                                      User.is_active.is_(True))
            for user in (await db.execute(stmt)).scalars():
                user.is_active = False
                user.soft_delete()
        await db.commit()
    await engine.dispose()


def superadmin_client() -> httpx.Client:
    sa = client()
    resp = sa.post("/api/v1/auth/login", json={"email": "superadmin@stag.local", "password": "Super@123"})
    if resp.status_code == 200:
        sa.headers["Authorization"] = f"Bearer {resp.json()['data']['access_token']}"
        print("PASS login superadmin@stag.local: 200")
        return sa
    print(f"WARN seeded superadmin login failed ({resp.status_code}: {resp.json().get('message')}) "
          "— using a temporary superadmin")
    asyncio.run(_temp_superadmin(True))
    login(sa, TEMP_SA_EMAIL, TEMP_SA_PASSWORD)
    return sa


def branches_checks(owner: httpx.Client, trainer: httpx.Client, me: dict) -> None:
    print("\n── branches ──")
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    listed = check("list branches", owner.get("/api/v1/branches", params={"page_size": 500}))
    main_row = next((b for b in listed.get("data", []) if b["id"] == main_branch["id"]), {})
    expect("main branch shows owner login email", main_row.get("login_email") == "owner@gym.com", main_row)
    expect("no password in branch list", all("password" not in k for b in listed["data"] for k in b))

    name, email = f"Smoke Branch {RUN}", f"branch{RUN}@stagsmoke.in"
    created = check("create branch", owner.post("/api/v1/branches", json={
        "branch_name": name, "location": "Smoke Street", "login_email": email, "login_password": "secret1"}), 201)
    branch = created.get("data") or {}
    expect("created branch login_email", branch.get("login_email") == email, branch)
    check("duplicate branch name", owner.post("/api/v1/branches", json={
        "branch_name": name.upper(), "location": "x", "login_email": f"other{RUN}@stagsmoke.in",
        "login_password": "secret1"}), 409)
    check("duplicate login email", owner.post("/api/v1/branches", json={
        "branch_name": f"{name} B", "login_email": "owner@gym.com", "login_password": "secret1"}), 409)
    check("short password", owner.post("/api/v1/branches", json={
        "branch_name": f"{name} C", "login_email": f"c{RUN}@stagsmoke.in", "login_password": "123"}), 422)
    check("bad email", owner.post("/api/v1/branches", json={
        "branch_name": f"{name} D", "login_email": "not-an-email", "login_password": "secret1"}), 422)
    check("trainer cannot create branch", trainer.post("/api/v1/branches", json={
        "branch_name": f"{name} T", "login_email": f"t{RUN}@stagsmoke.in", "login_password": "secret1"}), 403)

    bid = branch["id"]
    upd = check("rename branch", owner.put(f"/api/v1/branches/{bid}",
                                           json={"branch_name": f"{name} R", "location": "New Street"}))
    expect("rename applied", upd.get("data", {}).get("branch_name") == f"{name} R", upd)
    check("rename to existing name", owner.put(f"/api/v1/branches/{bid}", json={"branch_name": "Main Branch"}), 409)
    check("get branch", owner.get(f"/api/v1/branches/{bid}"))

    branch_login = client()
    login(branch_login, email, "secret1")
    check("reset branch login password", owner.post(f"/api/v1/branches/{bid}/reset-login-password",
                                                    json={"new_password": "newpass9"}))
    check("old branch session revoked", branch_login.get("/api/v1/auth/me"), 401)
    login(client(), email, "secret1", 401)
    login(client(), email, "newpass9")
    check("reset password too short", owner.post(f"/api/v1/branches/{bid}/reset-login-password",
                                                 json={"new_password": "1"}), 422)
    check("reset own login refused", owner.post(f"/api/v1/branches/{main_branch['id']}/reset-login-password",
                                                json={"new_password": "whatever1"}), 400)

    check("delete own home branch refused", owner.delete(f"/api/v1/branches/{main_branch['id']}"), 400)
    check("trainer cannot delete branch", trainer.delete(f"/api/v1/branches/{bid}"), 403)
    check("delete branch", owner.delete(f"/api/v1/branches/{bid}"))
    check("deleted branch gone", owner.get(f"/api/v1/branches/{bid}"), 404)
    login(client(), email, "newpass9", 401)
    check("deleted branch rejected as X-Branch-ID", owner.get("/api/v1/plans", headers={"X-Branch-ID": bid}), 403)


def organization_checks(owner: httpx.Client) -> None:
    print("\n── organizations ──")
    check("owner cannot list organizations", owner.get("/api/v1/organizations"), 403)
    try:
        sa = superadmin_client()
        _organization_checks(owner, sa)
    finally:
        asyncio.run(_temp_superadmin(False))


def _organization_checks(owner: httpx.Client, sa: httpx.Client) -> None:
    check("superadmin has no branches", sa.get("/api/v1/branches"), 403)
    check("list organizations", sa.get("/api/v1/organizations"))
    code, email = f"SMK{RUN}", f"gymowner{RUN}@stagsmoke.in"
    payload = {"name": f"Smoke Gym {RUN}", "code": code.lower(), "contact_email": f"info{RUN}@stagsmoke.in",
               "contact_phone": phone(90), "branch_name": "HQ", "branch_location": "Centre",
               "owner_name": "Smoke Owner", "owner_email": email, "owner_password": "gymown1"}
    org = check("onboard organization", sa.post("/api/v1/organizations", json=payload), 201).get("data") or {}
    expect("org code upper-cased", org.get("code") == code, org)
    expect("onboard returns owner + branch", org.get("owner_email") == email and org.get("branch_name") == "HQ", org)
    check("duplicate org code", sa.post("/api/v1/organizations", json={**payload, "owner_email": f"x{email}"}), 409)
    check("duplicate owner email", sa.post("/api/v1/organizations", json={**payload, "code": f"Z{code}"}), 409)
    check("onboard missing owner", sa.post("/api/v1/organizations", json={"name": "x", "code": "xy"}), 422)

    gym = client()
    login(gym, email, "gymown1")
    rows = check("new org lists its own branches", gym.get("/api/v1/branches")).get("data", [])
    expect("new org sees exactly 1 branch (tenant isolation)", len(rows) == 1 and rows[0]["login_email"] == email,
           rows)
    resp = check("delete last branch refused", gym.delete(f"/api/v1/branches/{org['branch_id']}"), 400)
    expect("last-branch message", "last branch" in (resp.get("message") or ""), resp)
    check("cross-tenant branch access", gym.get(f"/api/v1/branches/{owner_branch_id}"), 404)


def plan_checks(owner: httpx.Client, trainer: httpx.Client, me: dict) -> None:
    print("\n── plans ──")
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    base = {"name": f"Smoke Monthly {RUN}", "type": "MEMBERSHIP", "service_type": "GENERAL",
            "duration_days": 30, "price": 1499.5, "description": "smoke"}
    plan = check("create membership plan", owner.post("/api/v1/plans", json=base), 201).get("data") or {}
    expect("price is float", plan.get("price") == 1499.5, plan)
    pt = check("create PT plan", owner.post("/api/v1/plans", json={
        "name": f"Smoke PT {RUN}", "type": "ADD_ON", "service_type": "PERSONAL_TRAINING",
        "duration_days": 30, "price": 5000, "total_sessions": 12}), 201).get("data") or {}
    check("membership must be GENERAL", owner.post("/api/v1/plans", json={**base, "service_type": "DIET"}), 422)
    check("PT needs sessions", owner.post("/api/v1/plans", json={
        **base, "type": "ADD_ON", "service_type": "PERSONAL_TRAINING", "total_sessions": 0}), 422)
    check("duration >= 1", owner.post("/api/v1/plans", json={**base, "duration_days": 0}), 422)
    check("price >= 0", owner.post("/api/v1/plans", json={**base, "price": -1}), 422)
    check("bad type", owner.post("/api/v1/plans", json={**base, "type": "WEEKLY"}), 422)
    check("create needs a branch (All Branches)", owner.post("/api/v1/plans", json=base,
                                                             headers={"X-Branch-ID": ""}), 400)

    listed = check("list ADD_ON PT plans", owner.get("/api/v1/plans", params={
        "type": "ADD_ON", "service_type": "PERSONAL_TRAINING", "search": f"PT {RUN}"}))
    expect("filter finds PT plan", [p["id"] for p in listed.get("data", [])] == [pt.get("id")], listed)
    listed = check("list MEMBERSHIP search", owner.get("/api/v1/plans", params={"type": "MEMBERSHIP",
                                                                               "search": RUN}))
    expect("type filter excludes add-ons", [p["id"] for p in listed.get("data", [])] == [plan.get("id")], listed)
    check("get plan", owner.get(f"/api/v1/plans/{plan['id']}"))
    upd = check("update plan price", owner.put(f"/api/v1/plans/{plan['id']}", json={"price": 1599}))
    expect("price updated", upd.get("data", {}).get("price") == 1599.0, upd)
    check("update PT sessions to 0 refused", owner.put(f"/api/v1/plans/{pt['id']}", json={"total_sessions": 0}), 422)
    check("update membership to DIET refused", owner.put(f"/api/v1/plans/{plan['id']}",
                                                         json={"service_type": "DIET"}), 422)
    check("trainer cannot see other-branch plan", trainer.get(f"/api/v1/plans/{plan['id']}"), 404)

    spare = check("create spare plan", owner.post("/api/v1/plans", json={**base, "name": f"Spare {RUN}"}),
                  201).get("data") or {}
    check("delete unused plan", owner.delete(f"/api/v1/plans/{spare['id']}"))
    check("deleted plan gone", owner.get(f"/api/v1/plans/{spare['id']}"), 404)

    member = check("create member for usage", owner.post("/api/v1/members", json={
        "name": "Plan User", "phone": phone(1)}), 201).get("data") or {}
    asyncio.run(_attach_usage(me["user"]["organization_id"], main_branch["id"], member["id"], plan["id"], pt["id"]))
    check("delete plan with subscription refused", owner.delete(f"/api/v1/plans/{plan['id']}"), 400)
    check("delete plan with PT subscription refused", owner.delete(f"/api/v1/plans/{pt['id']}"), 400)


def lead_checks(owner: httpx.Client, trainer: httpx.Client) -> None:
    print("\n── leads ──")
    today = date.today()
    base = {"name": f"Smoke Lead {RUN}", "phone": phone(10), "location": "Anna Nagar", "goal": "Weight loss",
            "status": "NEW", "plan_to_join_date": str(today + timedelta(days=7)),
            "next_follow_up_date": str(today + timedelta(days=2)), "notes": "Walk-in enquiry"}
    lead = check("create lead", owner.post("/api/v1/leads", json=base), 201).get("data") or {}
    check("lead phone must be 10 digits", owner.post("/api/v1/leads", json={**base, "phone": "12345"}), 422)
    check("lead location required", owner.post("/api/v1/leads", json={**base, "location": ""}), 422)
    check("lead next follow-up required", owner.post("/api/v1/leads",
                                                     json={k: v for k, v in base.items()
                                                           if k != "next_follow_up_date"}), 422)
    rejected = check("create rejected lead", owner.post("/api/v1/leads", json={
        **base, "name": f"Smoke Rejected {RUN}", "phone": phone(11), "status": "NOT_INTERESTED"}),
        201).get("data") or {}

    ids = lambda body: {x["id"] for x in body.get("data", [])}  # noqa: E731
    all_ = check("list leads search", owner.get("/api/v1/leads", params={"search": RUN}))
    expect("search finds both", {lead.get("id"), rejected.get("id")} <= ids(all_), all_)
    rej = check("filter rejected", owner.get("/api/v1/leads", params={"filter": "rejected", "search": RUN}))
    expect("rejected filter", ids(rej) == {rejected.get("id")}, rej)
    fu = check("filter followup", owner.get("/api/v1/leads", params={"filter": "followup", "search": RUN}))
    expect("followup filter includes NEW lead with next date", lead.get("id") in ids(fu), fu)
    check("bad filter", owner.get("/api/v1/leads", params={"filter": "nope"}), 422)

    upd = check("update lead", owner.put(f"/api/v1/leads/{lead['id']}", json={"goal": "Muscle gain"}))
    expect("update applied", upd.get("data", {}).get("goal") == "Muscle gain", upd)
    check("follow-up needs notes", owner.post(f"/api/v1/leads/{lead['id']}/follow-up", json={}), 422)
    f1 = check("follow-up 1", owner.post(f"/api/v1/leads/{lead['id']}/follow-up", json={
        "notes": "Called, interested", "next_follow_up_date": str(today + timedelta(days=3))})).get("data") or {}
    expect("status defaults FOLLOW_UP", f1.get("status") == "FOLLOW_UP", f1)
    expect("last follow-up = today", f1.get("last_follow_up_date") == str(today), f1)
    expect("note appended", (f1.get("notes") or "").endswith(f"{today}: Called, interested")
           and "\n---\n" in f1.get("notes", ""), f1)

    conv = check("convert lead", owner.post(f"/api/v1/leads/{lead['id']}/convert")).get("data") or {}
    expect("converted: JOINED + registration id", conv.get("status") == "JOINED"
           and (conv.get("registration_id") or "").startswith("SG-") and conv.get("next_follow_up_date") is None
           and conv.get("converted_member_id") == conv.get("member_id"), conv)
    expect("conversion note", f"Converted to Member. Registration ID: {conv.get('registration_id')}"
           in (conv.get("notes") or ""), conv)
    m = check("converted member exists", owner.get(f"/api/v1/members/{conv.get('member_id')}")).get("data") or {}
    expect("member carries lead phone", m.get("phone") == base["phone"], m)
    check("convert again refused", owner.post(f"/api/v1/leads/{lead['id']}/convert"), 409)

    dup = check("lead with member's phone", owner.post("/api/v1/leads", json={
        **base, "name": f"Smoke Dup {RUN}"}), 201).get("data") or {}
    check("convert with existing member phone refused", owner.post(f"/api/v1/leads/{dup['id']}/convert"), 409)

    check("trainer cannot see other-branch lead", trainer.get(f"/api/v1/leads/{dup['id']}"), 404)
    check("trainer lists own-branch leads", trainer.get("/api/v1/leads"))
    check("delete lead", owner.delete(f"/api/v1/leads/{dup['id']}"))
    check("deleted lead gone", owner.get(f"/api/v1/leads/{dup['id']}"), 404)


owner_branch_id = ""


def main() -> None:
    global owner_branch_id
    owner = client()
    login(owner, "owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    owner_branch_id = main_branch["id"]
    owner.headers["X-Branch-ID"] = main_branch["id"]
    trainer = client()
    login(trainer, "trainer@gym.com", "trainer123")

    branches_checks(owner, trainer, me)
    organization_checks(owner)
    plan_checks(owner, trainer, me)
    lead_checks(owner, trainer)

    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
