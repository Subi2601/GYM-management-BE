"""Billing-core smoke test (subscriptions, payments, invoice, stats, personal training, dashboard).

    python -m scripts.smoke_billing [base_url]

Needs a running server and the seeded DB. Re-runnable: every run creates fresh members / trainers with
random phone numbers. Trainers are created through POST /employees; if that API is unavailable they are
inserted directly with SQLAlchemy (employee_code SMK-xxx).
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import date, timedelta
from uuid import UUID

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8012"
failures = 0


def check(label: str, resp: httpx.Response, expect: int = 200) -> dict:
    global failures
    ok = resp.status_code == expect
    if not ok:
        failures += 1
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    print(f"{'PASS' if ok else 'FAIL'} {label}: {resp.status_code} {'' if ok else body}")
    return body


def expect(label: str, cond: bool, detail: object = "") -> None:
    global failures
    if not cond:
        failures += 1
    print(f"{'PASS' if cond else 'FAIL'} {label} {'' if cond else detail}")


def phone() -> str:
    return "9" + "".join(random.choices("0123456789", k=9))


def login(client: httpx.Client, email: str, password: str) -> None:
    body = check(f"login {email}", client.post("/api/v1/auth/login", json={"email": email, "password": password}))
    client.headers["Authorization"] = f"Bearer {body['data']['access_token']}"


# ── DB helpers (plans lookup + trainer fallback) ─────────────────────────────
async def _db_plans(branch_id: UUID) -> dict[str, str]:
    from sqlalchemy import select

    from app.database import AsyncSessionLocal, engine
    from app.models.billing import Plan

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Plan.name, Plan.id).where(
            Plan.branch_id == branch_id, Plan.is_delete.is_(False)))).all()
    await engine.dispose()   # each asyncio.run() is a new loop — never reuse pooled connections across loops
    return {name: str(pid) for name, pid in rows}


async def _db_employee(branch_id: UUID, role: str, name: str) -> str:
    from sqlalchemy import select

    from app.core.enums import EmployeeRole, EmployeeStatus
    from app.database import AsyncSessionLocal, engine
    from app.models.organization import Branch
    from app.models.staff import Employee

    async with AsyncSessionLocal() as db:
        branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one()
        emp = Employee(organization_id=branch.organization_id, branch_id=branch_id,
                       employee_code=f"SMK-{random.randint(0, 99999):05d}", name=name, phone=phone(),
                       role=EmployeeRole(role), status=EmployeeStatus.ACTIVE, date_of_joining=date.today())
        db.add(emp)
        await db.commit()
        emp_id = str(emp.id)
    await engine.dispose()
    return emp_id


def make_employee(client: httpx.Client, branch_id: str, role: str, name: str) -> str:
    resp = client.post("/api/v1/employees", json={
        "name": name, "phone": phone(), "email": f"smk{random.randint(0, 10**8)}@example.com",
        "address": "Smoke street", "role": role, "aadhar_number": "".join(random.choices("0123456789", k=12)),
        "pan_number": "ABCDE1234F",
        "emergency_contact_name": "Kin", "emergency_contact_phone": phone(), "emergency_contact_relation": "Brother",
        "date_of_joining": str(date.today()), "morning_start": "06:00", "morning_end": "10:00",
        "evening_start": "17:00", "evening_end": "21:00"})
    if resp.status_code == 201:
        print(f"     {role} {name} created via API")
        return resp.json()["data"]["id"]
    print(f"     employees API unavailable ({resp.status_code}) — inserting {role} via SQLAlchemy")
    return asyncio.run(_db_employee(UUID(branch_id), role, name))


def make_member(client: httpx.Client, name: str) -> tuple[str, str]:
    ph = phone()
    body = check(f"create member {name}", client.post("/api/v1/members", json={"name": name, "phone": ph}), 201)
    return body["data"]["id"], ph


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=30)
    login(owner, "owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    branch_id = main_branch["id"]

    # Writes with "All Branches" (no X-Branch-ID for an owner) are refused
    check("enrol without a branch → 400", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": str(UUID(int=1)), "plan_ids": [str(UUID(int=2))],
        "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 400)
    owner.headers["X-Branch-ID"] = branch_id

    plans = asyncio.run(_db_plans(UUID(branch_id)))
    monthly, quarterly = plans["Monthly Membership"], plans["Quarterly Membership"]
    pt_plan, diet = plans["Personal Training - 12 Sessions"], plans["Diet Plan - Standard"]

    trainer1 = make_employee(owner, branch_id, "TRAINER", "Smoke Trainer One")
    trainer2 = make_employee(owner, branch_id, "TRAINER", "Smoke Trainer Two")
    cleaner = make_employee(owner, branch_id, "CLEANER", "Smoke Cleaner")

    # ── atomic enrolment: Monthly (1500) + PT (6000), discount 500, paid 6000 → balance 1000 ──
    tag = f"Billing{random.randint(1000, 9999)}"
    member_id, member_phone = make_member(owner, f"{tag} Alpha")
    enrol = check("enrol membership + PT", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": member_id, "plan_ids": [monthly, pt_plan], "trainer_id": trainer1,
        "payment": {"discount_amount": 500, "discount_reason": "Festival offer", "paid_amount": 6000,
                    "payment_mode": "BANK_TRANSFER", "balance_due_date": str(date.today() + timedelta(days=10))}}),
        201)["data"]
    expect("enrol amounts", (enrol["amount"], enrol["discount_amount"], enrol["paid_amount"],
                             enrol["balance_amount"]) == (7500, 500, 6000, 1000), enrol)
    expect("enrol created 2 subs + 1 PT", len(enrol["subscription_ids"]) == 2
           and len(enrol["pt_subscription_ids"]) == 1, enrol)
    expect("receipt format", enrol["receipt_no"].startswith("REC-") and len(enrol["receipt_no"]) >= 8, enrol)
    payment_id, pt_id = enrol["payment_id"], enrol["pt_subscription_ids"][0]

    inv = check("invoice", owner.get(f"/api/v1/payments/{payment_id}/invoice"))["data"]
    expect("invoice totals", (inv["gross"], inv["discount_amount"], inv["net_amount"], inv["paid_amount"],
                              inv["balance_amount"]) == (7500, 500, 7000, 6000, 1000), inv)
    expect("invoice lines", sorted(l["plan_name"] for l in inv["lines"])
           == ["Monthly Membership", "Personal Training - 12 Sessions"], inv["lines"])
    expect("invoice header", inv["receipt_no"] == enrol["receipt_no"] and inv["branch_name"] == "Main Branch"
           and inv["member"]["phone"] == member_phone and inv["organization_name"], inv)
    monthly_line = next(l for l in inv["lines"] if l["plan_name"] == "Monthly Membership")
    expect("end date = start + duration days",
           date.fromisoformat(monthly_line["end_date"]) - date.fromisoformat(monthly_line["start_date"])
           == timedelta(days=30), monthly_line)

    stats = check("payment stats", owner.get("/api/v1/payments/stats"))["data"]
    expect("stats today ≥ 6000 and non-cash counted", stats["today"] >= 6000 and stats["today_account"] >= 6000
           and stats["total"] >= stats["last_12_months"] >= stats["this_month"] >= stats["today"], stats)

    board = check("subscriptions board", owner.get("/api/v1/subscriptions", params={"search": member_phone}))
    expect("board: one latest row per member", board["total"] == 1, board)
    row = board["data"][0]
    expect("board row derived fields", row["payment_status"] == "PAID" and row["renewal_state"] == "NONE"
           and row["days_left"] == 30 and row["member_phone"] == member_phone, row)
    check("board renewal_state filter", owner.get("/api/v1/subscriptions", params={"renewal_state": "EXPIRED"}))
    check("board bad renewal_state → 422", owner.get("/api/v1/subscriptions", params={"renewal_state": "X"}), 422)

    history = check("member history", owner.get(f"/api/v1/subscriptions/member/{member_id}"))["data"]
    expect("history has 2 subscriptions", len(history) == 2, history)
    pt_sub_id = next(s["id"] for s in history if s["service_type"] == "PERSONAL_TRAINING")
    detail = check("subscription detail", owner.get(f"/api/v1/subscriptions/{pt_sub_id}"))["data"]
    expect("detail: plans, payment, PT link", len(detail["plans"]) == 2 and detail["payment"]["receipt_no"]
           == enrol["receipt_no"] and detail["pt_subscription_id"] == pt_id, detail)
    check("detail unknown → 404", owner.get(f"/api/v1/subscriptions/{UUID(int=7)}"), 404)

    payments = check("payments list", owner.get("/api/v1/payments", params={"search": member_phone}))
    expect("payments list row", payments["total"] == 1 and sorted(payments["data"][0]["plan_names"])
           == ["Monthly Membership", "Personal Training - 12 Sessions"], payments)
    check("payments filter mode/date", owner.get("/api/v1/payments", params={
        "payment_mode": "BANK_TRANSFER", "date_from": str(date.today()), "date_to": str(date.today())}))
    check("payments bad date range → 400", owner.get("/api/v1/payments", params={
        "date_from": str(date.today()), "date_to": str(date.today() - timedelta(days=1))}), 400)

    # ── personal training ──
    pts = check("PT list (active + paid)", owner.get("/api/v1/personal-training", params={"search": member_phone}))
    expect("PT list row", pts["total"] == 1 and pts["data"][0]["trainer_name"] == "Smoke Trainer One"
           and pts["data"][0]["sessions_remaining"] == 12 and pts["data"][0]["is_paid"], pts)
    s1 = check("log session 1", owner.post(f"/api/v1/personal-training/{pt_id}/sessions", json={
        "trainer_verified": True, "client_verified": True, "notes": "Legs"}), 201)["data"]
    s2 = check("log session 2 (trainer change)", owner.post(f"/api/v1/personal-training/{pt_id}/sessions", json={
        "session_date": str(date.today()), "trainer_id": trainer2, "notes": "Back"}), 201)["data"]
    expect("sessions decremented", (s1["sessions_remaining"], s2["sessions_remaining"]) == (11, 10)
           and s2["trainer_name"] == "Smoke Trainer Two" and s2["sessions_used"] == 2, (s1, s2))
    hist = check("session history", owner.get(f"/api/v1/personal-training/{pt_id}/sessions"))["data"]
    expect("history rows", len(hist) == 2 and sorted(h["sessions_remaining_after"] for h in hist) == [10, 11]
           and {h["trainer_name"] for h in hist} == {"Smoke Trainer One", "Smoke Trainer Two"}, hist)
    ch = check("change trainer", owner.post(f"/api/v1/personal-training/{pt_id}/trainer",
                                            json={"trainer_id": trainer1}))["data"]
    expect("trainer changed", ch["trainer_name"] == "Smoke Trainer One", ch)
    check("change trainer to non-trainer → 404", owner.post(f"/api/v1/personal-training/{pt_id}/trainer",
                                                             json={"trainer_id": cleaner}), 404)
    check("future session date → 400", owner.post(f"/api/v1/personal-training/{pt_id}/sessions", json={
        "session_date": str(date.today() + timedelta(days=2))}), 400)

    # ── validation errors on enrolment ──
    m2, m2_phone = make_member(owner, f"{tag} Beta")
    enrol_url = "/api/v1/subscriptions/enroll"
    check("discount > gross → 400", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [monthly], "payment": {"discount_amount": 2000, "paid_amount": 0,
                                                            "payment_mode": "CASH"}}), 400)
    check("paid > net → 400", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [monthly], "payment": {"discount_amount": 500, "paid_amount": 1200,
                                                            "payment_mode": "CASH"}}), 400)
    check("negative discount → 422", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [monthly], "payment": {"discount_amount": -1, "paid_amount": 0,
                                                            "payment_mode": "CASH"}}), 422)
    check("duplicate plan ids → 422", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [monthly, monthly], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}),
        422)
    check("empty plan ids → 422", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 422)
    check("unknown plan → 404", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [str(UUID(int=3))], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}),
        404)
    check("bad payment mode → 422", owner.post(enrol_url, json={
        "member_id": m2, "plan_ids": [monthly], "payment": {"paid_amount": 0, "payment_mode": "CHEQUE"}}), 422)
    expect("failed enrolments left nothing behind",
           owner.get(f"/api/v1/subscriptions/member/{m2}").json()["data"] == [])

    # ── unpaid subscription (old flow) → pay later via POST /payments ──
    unpaid = check("create unpaid PT subscription", owner.post("/api/v1/subscriptions", json={
        "member_id": m2, "plan_id": pt_plan, "discount_amount": 1000, "discount_reason": "Referral",
        "trainer_id": trainer1}), 201)["data"]
    expect("unpaid subscription is PENDING", unpaid["payment_status"] == "PENDING"
           and unpaid["pt_subscription_id"], unpaid)
    unpaid_pt = unpaid["pt_subscription_id"]
    hidden = owner.get("/api/v1/personal-training", params={"search": m2_phone}).json()
    expect("unpaid PT hidden from default PT list", hidden["total"] == 0, hidden)
    shown = owner.get("/api/v1/personal-training", params={"search": m2_phone, "paid_only": "false"}).json()
    expect("unpaid PT listed with paid_only=false", shown["total"] == 1 and not shown["data"][0]["is_paid"], shown)
    check("log session on unpaid PT → 400", owner.post(f"/api/v1/personal-training/{unpaid_pt}/sessions",
                                                       json={}), 400)
    check("pay linked PT directly → 400", owner.post("/api/v1/payments", json={
        "pt_subscription_id": unpaid_pt, "paid_amount": 100, "payment_mode": "CASH"}), 400)
    check("pay with both targets → 422", owner.post("/api/v1/payments", json={
        "subscription_ids": [unpaid["id"]], "pt_subscription_id": unpaid_pt, "paid_amount": 1,
        "payment_mode": "CASH"}), 422)
    check("pay with no target → 422", owner.post("/api/v1/payments", json={"paid_amount": 1,
                                                                           "payment_mode": "CASH"}), 422)
    paid = check("pay unpaid subscription (stored discount)", owner.post("/api/v1/payments", json={
        "subscription_ids": [unpaid["id"]], "paid_amount": 5000, "payment_mode": "CASH"}), 201)["data"]
    expect("payment uses stored discount", (paid["amount"], paid["discount_amount"], paid["balance_amount"])
           == (6000, 1000, 0) and paid["plan_names"] == ["Personal Training - 12 Sessions"], paid)
    check("pay again → 409", owner.post("/api/v1/payments", json={
        "subscription_ids": [unpaid["id"]], "paid_amount": 0, "payment_mode": "CASH"}), 409)
    check("log session on now-paid PT", owner.post(f"/api/v1/personal-training/{unpaid_pt}/sessions", json={}), 201)

    # ── direct PT subscription (unpaid) → pay via pt_subscription_id ──
    m3, m3_phone = make_member(owner, f"{tag} Gamma")
    check("PT subscribe non-PT plan → 400", owner.post("/api/v1/personal-training/subscribe", json={
        "member_id": m3, "trainer_id": trainer1, "plan_id": diet}), 400)
    check("PT subscribe with cleaner → 404", owner.post("/api/v1/personal-training/subscribe", json={
        "member_id": m3, "trainer_id": cleaner, "plan_id": pt_plan}), 404)
    direct = check("PT subscribe", owner.post("/api/v1/personal-training/subscribe", json={
        "member_id": m3, "trainer_id": trainer2, "plan_id": pt_plan, "goal": "WEIGHT_LOSS"}), 201)["data"]
    expect("direct PT unpaid, 12 sessions, 30-day expiry", not direct["is_paid"] and direct["total_sessions"] == 12
           and date.fromisoformat(direct["expiry_date"]) - date.fromisoformat(direct["start_date"])
           == timedelta(days=30), direct)
    check("PT pay discount > price → 400", owner.post("/api/v1/payments", json={
        "pt_subscription_id": direct["id"], "discount_amount": 7000, "paid_amount": 0, "payment_mode": "UPI"}), 400)
    pp = check("pay PT subscription", owner.post("/api/v1/payments", json={
        "pt_subscription_id": direct["id"], "discount_amount": 0, "paid_amount": 6000, "payment_mode": "UPI"}),
        201)["data"]
    expect("PT payment row", pp["pt_subscription_id"] == direct["id"] and pp["balance_amount"] == 0, pp)
    check("pay PT again → 409", owner.post("/api/v1/payments", json={
        "pt_subscription_id": direct["id"], "paid_amount": 0, "payment_mode": "UPI"}), 409)
    pinv = check("PT invoice", owner.get(f"/api/v1/payments/{pp['id']}/invoice"))["data"]
    expect("PT invoice line", len(pinv["lines"]) == 1 and pinv["lines"][0]["total_sessions"] == 12, pinv)

    # ── expired PT: start 60 days ago → logging marks EXPIRED (400), then "not active" (400) ──
    old = check("PT subscribe (backdated)", owner.post("/api/v1/personal-training/subscribe", json={
        "member_id": m3, "trainer_id": trainer1, "plan_id": pt_plan,
        "start_date": str(date.today() - timedelta(days=60))}), 201)["data"]
    check("pay backdated PT", owner.post("/api/v1/payments", json={
        "pt_subscription_id": old["id"], "paid_amount": 6000, "payment_mode": "CARD"}), 201)
    check("log on expired PT → 400", owner.post(f"/api/v1/personal-training/{old['id']}/sessions", json={}), 400)
    expired = owner.get("/api/v1/personal-training", params={"search": m3_phone, "status": "EXPIRED"}).json()
    expect("expired PT persisted as EXPIRED", expired["total"] == 1 and expired["data"][0]["id"] == old["id"],
           expired)
    check("log on inactive PT → 400", owner.post(f"/api/v1/personal-training/{old['id']}/sessions", json={}), 400)

    # ── dashboard ──
    dash = check("dashboard summary", owner.get("/api/v1/dashboard/summary"))["data"]
    this_month = f"{date.today():%b %Y}"
    expect("dashboard shape", len(dash["growth"]) == 6 and dash["growth"][-1]["month"] == this_month
           and dash["growth"][-1]["new_members"] >= 3 and dash["growth"][-1]["revenue"] >= 23000
           and dash["active_members"] >= 1 and dash["total_revenue"] >= dash["today_revenue"] >= 23000, dash)
    owner.headers.pop("X-Branch-ID")
    check("dashboard all branches", owner.get("/api/v1/dashboard/summary"))

    # ── trainer account: no stats / dashboard / payment list; other branch invisible ──
    trainer = httpx.Client(base_url=BASE, timeout=30)
    login(trainer, "trainer@gym.com", "trainer123")
    check("trainer: stats forbidden", trainer.get("/api/v1/payments/stats"), 403)
    check("trainer: dashboard forbidden", trainer.get("/api/v1/dashboard/summary"), 403)
    check("trainer: payments list forbidden", trainer.get("/api/v1/payments"), 403)
    check("trainer: invoice of other branch → 404", trainer.get(f"/api/v1/payments/{payment_id}/invoice"), 404)
    check("trainer: board ok", trainer.get("/api/v1/subscriptions"))
    check("trainer: PT of other branch → 404", trainer.get(f"/api/v1/personal-training/{pt_id}/sessions"), 404)

    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
