"""Smoke test: plan categories, calendar-month plans, hidden plans, ID check, group packages, offer categories,
all-branches check-in.

    python -m scripts.smoke_plans_groups [base_url]

Needs the STAG tariff loaded (python -m scripts.load_stag_tariff). Fresh names / phones every run.
"""
from __future__ import annotations

import sys
import time
from datetime import date

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
    return f"5{_seq % 10**9:09d}"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    token = check("login", c.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    c.headers["Authorization"] = f"Bearer {token['data']['access_token']}"
    me = check("me", c.get("/api/v1/auth/me"))["data"]
    branch = {b["branch_name"]: b["id"] for b in me["branches"]}
    c.headers["X-Branch-ID"] = branch["Main Branch"]

    # ── categories (owner master) ──
    print("\n── categories ──")
    cats = check("list categories", c.get("/api/v1/plan-categories"))["data"]
    by_name = {x["name"]: x for x in cats}
    expect("defaults present with counts", {"General", "Couple", "Family", "Personal Training"} <= set(by_name)
           and by_name["General"]["plan_count"] >= 4, cats)
    new = check("add category", c.post("/api/v1/plan-categories", json={"name": f"Ladies only {RUN}"}), 201)["data"]
    check("duplicate name → 409", c.post("/api/v1/plan-categories", json={"name": f"ladies ONLY {RUN}"}), 409)
    ren = check("rename", c.put(f"/api/v1/plan-categories/{new['id']}", json={"name": f"Women only {RUN}"}))["data"]
    expect("renamed", ren["name"] == f"Women only {RUN}", ren)
    hid = check("hide", c.put(f"/api/v1/plan-categories/{new['id']}", json={"is_active": False}))["data"]
    expect("hidden", hid["is_active"] is False, hid)
    order = [x["id"] for x in check("list again", c.get("/api/v1/plan-categories"))["data"]]
    check("reorder (new first)", c.put("/api/v1/plan-categories/order", json={"ids": [new["id"]] + [i for i in order
                                                                                                if i != new["id"]]}))
    first = check("order applied", c.get("/api/v1/plan-categories"))["data"][0]
    expect("new category first", first["id"] == new["id"], first)
    check("reorder must list all → 400", c.put("/api/v1/plan-categories/order", json={"ids": [new["id"]]}), 400)
    check("put it back last", c.put("/api/v1/plan-categories/order", json={"ids": [i for i in order if i != new["id"]]
                                                                          + [new["id"]]}))
    check("delete category with plans → 400",
          c.delete(f"/api/v1/plan-categories/{by_name['General']['id']}"), 400)
    check("delete empty category", c.delete(f"/api/v1/plan-categories/{new['id']}"))

    # ── plans: months, hidden, rules ──
    print("\n── plans ──")
    gen = by_name["General"]["id"]
    two = check("2-month plan", c.post("/api/v1/plans", json={
        "name": f"Smoke 2 Months {RUN}", "category_id": gen, "duration_months": 2, "price": 3499}), 201)["data"]
    expect("months stored", two["duration_months"] == 2 and two["category_name"] == "General", two)
    check("no duration → 422", c.post("/api/v1/plans", json={"name": "x", "category_id": gen, "price": 1}), 422)
    check("group add-on → 422", c.post("/api/v1/plans", json={
        "name": "x", "category_id": gen, "type": "ADD_ON", "duration_days": 30, "price": 1, "group_size": 2}), 422)
    m = check("member", c.post("/api/v1/members", json={"name": f"Months {RUN}", "phone": phone()}), 201)["data"]
    e = check("enrol 31 Jan + 2 months", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": m["id"], "plan_ids": [two["id"]], "start_date": "2027-01-31",
        "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 201)["data"]
    sub = check("subscription", c.get(f"/api/v1/subscriptions/{e['subscription_ids'][0]}"))["data"]
    expect("calendar end 31 Mar", sub["end_date"] == "2027-03-31", sub)
    check("hide plan", c.put(f"/api/v1/plans/{two['id']}", json={"is_active": False}))
    check("hidden plan can't be sold → 400", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": m["id"], "plan_ids": [two["id"]], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 400)
    act = check("active_only list", c.get("/api/v1/plans", params={"active_only": True, "page_size": 200}))["data"]
    expect("hidden plan not in billing list", all(p["id"] != two["id"] for p in act), "")
    check("delete used plan → 400 (hide instead)", c.delete(f"/api/v1/plans/{two['id']}"), 400)

    def tariff(category: str, name: str) -> dict:
        rows = c.get("/api/v1/plans", params={"category_id": by_name[category]["id"], "page_size": 50}).json()["data"]
        return next(p for p in rows if p["name"] == name)

    # ── ID check ──
    print("\n── ID check ──")
    college = tariff("Student - College", "1 Month")
    s = check("student", c.post("/api/v1/members", json={"name": f"Student {RUN}", "phone": phone()}), 201)["data"]
    check("college plan without ID → 400", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": s["id"], "plan_ids": [college["id"]], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 400)
    check("with ID verified", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": s["id"], "plan_ids": [college["id"]], "id_verified": True,
        "payment": {"paid_amount": 1799, "payment_mode": "UPI"}}), 201)

    # ── group package ──
    print("\n── group package ──")
    couple = tariff("Couple", "3 Months")
    payer = check("payer", c.post("/api/v1/members", json={"name": f"Couple A {RUN}", "phone": phone()}), 201)["data"]
    partner_phone = phone()
    check("couple without partner → 400", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": payer["id"], "plan_ids": [couple["id"]], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 400)
    check("payer twice → 400", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": payer["id"], "plan_ids": [couple["id"]], "group_members": [{"member_id": payer["id"]}],
        "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 400)
    g = check("couple with new partner", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": payer["id"], "plan_ids": [couple["id"]],
        "group_members": [{"name": f"Couple B {RUN}", "phone": partner_phone}],
        "payment": {"paid_amount": 9499, "payment_mode": "CASH"}}), 201)["data"]
    expect("two memberships, one bill", len(g["subscription_ids"]) == 2 and g["amount"] == 9499, g)
    inv = check("invoice", c.get(f"/api/v1/payments/{g['payment_id']}/invoice"))["data"]
    expect("a line per member, shares add up", len(inv["lines"]) == 2
           and round(sum(l["price"] for l in inv["lines"]), 2) == 9499
           and any(f"Couple B {RUN}" in l["plan_name"] for l in inv["lines"]), inv["lines"])
    partner = c.get("/api/v1/members", params={"search": partner_phone}).json()["data"][0]
    expect("partner has own membership", partner["membership_state"] in ("ACTIVE", "EXPIRING")
           and partner["current_plan_id"] == couple["id"], partner)

    # ── offer limited to categories ──
    print("\n── offer categories ──")
    offer = check("offer on General only", c.post("/api/v1/offers", json={
        "name": f"Diwali Gen {RUN}", "discount_percent": 10, "category_ids": [gen]}), 201)["data"]
    expect("offer keeps categories", offer["category_ids"] == [gen], offer)
    one = tariff("General", "1 Month")
    pt = tariff("Personal Training", "Fit Start Program")
    o = check("offer member", c.post("/api/v1/members", json={"name": f"Offer {RUN}", "phone": phone()}), 201)["data"]
    r = check("General + PT with offer", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": o["id"], "plan_ids": [one["id"], pt["id"]],
        "payment": {"offer_id": offer["id"], "paid_amount": 0, "payment_mode": "CASH"}}), 201)["data"]
    expect("10% of General only", r["discount_amount"] == round(one["price"] * 0.10, 2), r)
    check("offer on a category not billed → 400", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": o["id"], "plan_ids": [pt["id"]],
        "payment": {"offer_id": offer["id"], "paid_amount": 0, "payment_mode": "CASH"}}), 400)

    # ── all branches ──
    print("\n── all-branches check-in ──")
    family = tariff("Family", "3 Months")
    fam = check("family payer", c.post("/api/v1/members", json={"name": f"Family A {RUN}", "phone": phone()}), 201)["data"]
    check("family of 3", c.post("/api/v1/subscriptions/enroll", json={
        "member_id": fam["id"], "plan_ids": [family["id"]],
        "group_members": [{"name": f"Family B {RUN}", "phone": phone()}, {"name": f"Family C {RUN}", "phone": phone()}],
        "payment": {"paid_amount": 13999, "payment_mode": "CASH"}}), 201)
    c.headers["X-Branch-ID"] = branch["North Branch"]
    visitors = check("North: visitors list", c.get("/api/v1/attendance/members/visitors"))["data"]
    expect("Main family member listed with home branch", any(v["id"] == fam["id"] and v["home_branch"] == "Main Branch"
                                                             for v in visitors), visitors)
    expect("non-all-branch member not listed", all(v["id"] != o["id"] for v in visitors), "")
    check("North: family member checks in", c.post("/api/v1/attendance/members/check-in", json={"member_id": fam["id"]}))
    day = check("North: members daily", c.get("/api/v1/attendance/members/daily"))["data"]
    expect("visit recorded at North", any(v["member_id"] == fam["id"] for v in day["records"]), "")
    check("North: General member refused → 404", c.post("/api/v1/attendance/members/check-in",
                                                        json={"member_id": o["id"]}), 404)
    check("North: family member checks out", c.post(f"/api/v1/attendance/members/{fam['id']}/check-out"))

    print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
