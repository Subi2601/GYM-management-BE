"""Smoke test: offers master + % discount, shared invoice link, renewals, staff logins.

    python -m scripts.smoke_members_extras [base_url]

Runs in North Branch with fresh names / phones / emails each run.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
RUN = int(time.time()) % 10**7
failures = 0
_seq = int(time.time() * 10) % 10**8


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
    print(f"{'PASS' if condition else 'FAIL'} {label}{'' if condition else f': {detail}'}")


def phone() -> str:
    global _seq
    _seq += 1
    return f"6{_seq % 10**9:09d}"


def login(email: str, password: str, expect_status: int = 200) -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=30)
    body = check(f"login {email}", c.post("/api/v1/auth/login", json={"email": email, "password": password}),
                 expect_status)
    if expect_status == 200:
        c.headers["Authorization"] = f"Bearer {body['data']['access_token']}"
    return c


def main() -> None:
    owner = login("owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    north = next(b for b in me["branches"] if b["branch_name"] == "North Branch")
    check("offer create needs a branch (All Branches)", owner.post("/api/v1/offers", json={
        "name": "X", "discount_percent": 10}), 400)
    owner.headers["X-Branch-ID"] = north["id"]
    today = date.today()

    # ── offers ──
    print("\n── offers ──")
    diwali = check("create offer", owner.post("/api/v1/offers", json={
        "name": f"Diwali {RUN}", "discount_percent": 15, "description": "Festival"}), 201)["data"]
    expect("offer available", diwali["available"] and diwali["discount_percent"] == 15, diwali)
    check("duplicate name → 409", owner.post("/api/v1/offers", json={"name": f"diwali {RUN}", "discount_percent": 5}), 409)
    check("percent > 100 → 422", owner.post("/api/v1/offers", json={"name": f"Bad {RUN}", "discount_percent": 120}), 422)
    check("percent 0 → 422", owner.post("/api/v1/offers", json={"name": f"Zero {RUN}", "discount_percent": 0}), 422)
    check("window reversed → 400", owner.post("/api/v1/offers", json={
        "name": f"Rev {RUN}", "discount_percent": 5, "valid_from": str(today), "valid_to": str(today - timedelta(days=1))}), 400)
    future = check("future offer", owner.post("/api/v1/offers", json={
        "name": f"NewYear {RUN}", "discount_percent": 20, "valid_from": str(today + timedelta(days=30))}), 201)["data"]
    expect("future offer not available yet", not future["available"], future)
    avail = check("available offers", owner.get("/api/v1/offers/available"))["data"]
    ids = {o["id"] for o in avail}
    expect("available lists Diwali, not future", diwali["id"] in ids and future["id"] not in ids, avail)
    upd = check("edit offer %", owner.put(f"/api/v1/offers/{diwali['id']}", json={"discount_percent": 10}))["data"]
    expect("edit applied", upd["discount_percent"] == 10, upd)
    counts = check("offer counts", owner.get("/api/v1/offers/counts"))["data"]
    expect("counts", counts["active"] >= 2 and counts["all"] >= counts["active"], counts)

    # ── enrol with the offer (server computes the discount) ──
    print("\n── enrol with offer ──")
    plans = check("plans", owner.get("/api/v1/plans", params={"page_size": 100}))["data"]
    monthly = next(p for p in plans if p["type"] == "MEMBERSHIP")
    member = check("create member", owner.post("/api/v1/members", json={"name": f"Offer Member {RUN}",
                                                                        "phone": phone()}), 201)["data"]
    expected = round(monthly["price"] * 0.10, 2)
    enrol = check("enrol with offer (fake discount ignored)", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": member["id"], "plan_ids": [monthly["id"]],
        "payment": {"offer_id": diwali["id"], "discount_amount": 99999, "paid_amount": 0, "payment_mode": "CASH"}}),
        201)["data"]
    expect("discount = 10% of price", abs(enrol["discount_amount"] - expected) < 0.01, (enrol, expected))
    check("deactivate offer", owner.patch(f"/api/v1/offers/{diwali['id']}/status", json={"is_active": False}))
    m2 = check("create member 2", owner.post("/api/v1/members", json={"name": f"Offer Member B {RUN}",
                                                                       "phone": phone()}), 201)["data"]
    check("enrol with inactive offer → 400", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": m2["id"], "plan_ids": [monthly["id"]],
        "payment": {"offer_id": diwali["id"], "paid_amount": 0, "payment_mode": "CASH"}}), 400)
    tab_inactive = check("inactive tab", owner.get("/api/v1/offers", params={"tab": "inactive", "search": str(RUN)}))
    expect("inactive tab lists it", any(o["id"] == diwali["id"] for o in tab_inactive["data"]), tab_inactive)

    # ── shared invoice ──
    print("\n── shared invoice ──")
    inv = check("invoice", owner.get(f"/api/v1/payments/{enrol['payment_id']}/invoice"))["data"]
    token = inv["share_token"]
    expect("invoice reason names the offer", (inv["discount_reason"] or "").startswith(f"Diwali {RUN}"), inv)
    anon = httpx.Client(base_url=BASE, timeout=30)
    pub = check("public invoice without login", anon.get(f"/api/v1/public/invoice/{token}"))["data"]
    expect("public invoice matches", pub["receipt_no"] == inv["receipt_no"], pub)
    bad = token[:-1] + ("0" if token[-1] != "0" else "1")
    check("tampered token → 404", anon.get(f"/api/v1/public/invoice/{bad}"), 404)
    check("short token → 422", anon.get("/api/v1/public/invoice/abc"), 422)

    # ── renewals ──
    print("\n── renewals ──")
    due_member = check("member ending soon", owner.post("/api/v1/members", json={"name": f"Renew Due {RUN}",
                                                                                 "phone": phone()}), 201)["data"]
    start = today - timedelta(days=monthly["duration_days"] - 3)   # ends in ~3 days
    check("enrol ending soon", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": due_member["id"], "plan_ids": [monthly["id"]], "start_date": str(start),
        "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 201)
    due = check("renewals due", owner.get("/api/v1/renewals", params={"tab": "due", "search": f"Renew Due {RUN}"}))
    row = next((r for r in due["data"] if r["member_id"] == due_member["id"]), None)
    expect("due row with days_left", row is not None and 0 <= row["days_left"] <= 7 and row["reminder_count"] == 0, due)
    if row:
        rem = check("mark reminded", owner.post(f"/api/v1/renewals/{row['subscription_id']}/remind"))["data"]
        expect("reminder stamped", rem["reminder_count"] == 1 and rem["reminded_at"], rem)
        reminded = check("reminded tab", owner.get("/api/v1/renewals", params={"tab": "reminded",
                                                                               "search": f"Renew Due {RUN}"}))
        expect("reminded tab lists it", any(r["member_id"] == due_member["id"] for r in reminded["data"]), reminded)
    rc = check("renewal counts", owner.get("/api/v1/renewals/counts", params={"within": 15}))["data"]
    expect("counts shape", {"due", "overdue", "reminded", "all"} <= set(rc) and rc["all"] >= rc["due"], rc)
    check("within out of range → 422", owner.get("/api/v1/renewals", params={"within": 0}), 422)

    # ── staff logins ──
    print("\n── staff logins ──")
    email = f"staff{RUN}@example.com"
    emp = check("create staff", owner.post("/api/v1/employees", json={
        "name": f"Login Staff {RUN}", "phone": phone(), "email": email, "address": "1 Gym Road", "role": "TRAINER",
        "date_of_joining": "2025-01-01", "morning_start": "06:00", "morning_end": "10:00",
        "evening_start": "17:00", "evening_end": "21:00"}), 201)["data"]
    info = check("login info (none yet)", owner.get(f"/api/v1/employees/{emp['id']}/login"))["data"]
    expect("no login, defaults TRAINER", not info["has_login"] and info["role"] == "TRAINER", info)
    check("create login without password → 400", owner.put(f"/api/v1/employees/{emp['id']}/login",
                                                           json={"role": "TRAINER"}), 400)
    check("short password → 422", owner.put(f"/api/v1/employees/{emp['id']}/login",
                                            json={"role": "TRAINER", "password": "short"}), 422)
    made = check("create login (role sent is ignored)", owner.put(f"/api/v1/employees/{emp['id']}/login",
                                                                  json={"role": "OWNER", "password": "Passw0rd!"}))
    expect("access from staff role = TRAINER", made["data"]["role"] == "TRAINER", made)
    expect("created", made["data"]["has_login"] and made["data"]["enabled"] and "Login created" in made["message"], made)
    staff = login(email, "Passw0rd!")
    sme = check("staff me", staff.get("/api/v1/auth/me"))["data"]
    expect("staff homed in North, can't switch", sme["user"]["branch_id"] == north["id"]
           and not sme["can_switch_branch"], sme)
    check("staff role has no staff list → 403", staff.get("/api/v1/employees"), 403)
    check("staff lists own-branch members", staff.get("/api/v1/members"))
    check("staff cannot manage logins", staff.get(f"/api/v1/employees/{emp['id']}/login"), 403)
    check("reset password", owner.put(f"/api/v1/employees/{emp['id']}/login",
                                      json={"role": "TRAINER", "password": "NewPassw0rd!"}))
    check("old session revoked", staff.get("/api/v1/auth/me"), 401)
    login(email, "Passw0rd!", 401)
    login(email, "NewPassw0rd!")
    check("staff role → Manager", owner.put(f"/api/v1/employees/{emp['id']}", json={"role": "MANAGER"}))
    adm = check("login after role change", owner.get(f"/api/v1/employees/{emp['id']}/login"))["data"]
    expect("job title change keeps the login role (Staff)", adm["role_name"] == "Staff", adm)
    check("staff role → Trainer", owner.put(f"/api/v1/employees/{emp['id']}", json={"role": "TRAINER"}))
    new_email = f"staff{RUN}b@example.com"
    check("staff email edit", owner.put(f"/api/v1/employees/{emp['id']}", json={"email": new_email}))
    login(new_email, "NewPassw0rd!")
    email = new_email
    check("disable login", owner.delete(f"/api/v1/employees/{emp['id']}/login"))
    login(email, "NewPassw0rd!", 401)
    check("re-enable", owner.put(f"/api/v1/employees/{emp['id']}/login", json={"role": "TRAINER"}))
    login(email, "NewPassw0rd!")
    check("terminate staff", owner.patch(f"/api/v1/employees/{emp['id']}/terminate"))
    login(email, "NewPassw0rd!", 401)
    check("terminated cannot get a login", owner.put(f"/api/v1/employees/{emp['id']}/login",
                                                     json={"role": "TRAINER", "password": "Passw0rd!"}), 400)

    print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
