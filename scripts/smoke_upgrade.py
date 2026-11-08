"""Smoke test: plan upgrades — window, credit, lower / shorter plans refused, balance billed, history, invoice.

    python -m scripts.smoke_upgrade [base_url]

Creates its own General plans (made inactive at the end) and fresh members every run.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
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


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    token = check("login", c.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    c.headers["Authorization"] = f"Bearer {token['data']['access_token']}"
    me = check("me", c.get("/api/v1/auth/me"))["data"]
    c.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["Main Branch"]
    gen = next(x["id"] for x in check("categories", c.get("/api/v1/plan-categories"))["data"] if x["name"] == "General")
    today = date.today()

    def plan(name: str, price: float, **duration) -> dict:
        return check(f"plan {name}", c.post("/api/v1/plans", json={
            "name": f"Up {name} {RUN}", "category_id": gen, "price": price, **duration}), 201)["data"]

    def member(label: str) -> dict:
        return check(f"member {label}", c.post("/api/v1/members", json={"name": f"Up {label} {RUN}",
                                                                         "phone": phone()}), 201)["data"]

    def enrol(m: dict, p: dict, start: date, paid: float, discount: float = 0) -> dict:
        return check(f"enrol {m['name']} on {p['name']}", c.post("/api/v1/subscriptions/enroll", json={
            "member_id": m["id"], "plan_ids": [p["id"]], "start_date": start.isoformat(),
            "payment": {"paid_amount": paid, "discount_amount": discount, "discount_reason": "Smoke",
                        "payment_mode": "CASH"}}), 201)["data"]

    def info(m: dict) -> dict:
        return check(f"upgrade info {m['name']}", c.get(f"/api/v1/subscriptions/member/{m['id']}/upgrade"))["data"]

    def upgrade(m: dict, p: dict, paid: float, status: int = 201) -> dict:
        return check(f"upgrade to {p['name']} → {status}", c.post("/api/v1/subscriptions/upgrade", json={
            "member_id": m["id"], "plan_id": p["id"], "payment": {"paid_amount": paid, "payment_mode": "UPI"}}),
            status).get("data") or {}

    print("\n── plans & default windows ──")
    one = plan("1 Month", 2000, duration_months=1)
    three = plan("3 Months", 5000, duration_months=3)
    six = plan("6 Months", 9000, duration_months=6)
    cheap = plan("3 Months Lite", 1500, duration_months=3)
    short = plan("15 Days Pro", 2500, duration_days=15)
    off = plan("1 Month No Upgrade", 2100, duration_months=1, upgrade_window_days=0)
    expect("1 month window 15", one["upgrade_window_days"] == 15, one)
    expect("3 months window 30", three["upgrade_window_days"] == 30, three)
    expect("6 months window 45", six["upgrade_window_days"] == 45, six)
    expect("15 days window 7", short["upgrade_window_days"] == 7, short)
    expect("explicit 0 kept", off["upgrade_window_days"] == 0, off)

    print("\n── upgrade inside the window ──")
    a = member("A")
    start = today - timedelta(days=5)
    enrol(a, one, start, paid=1800, discount=200)
    i = info(a)
    expect("can upgrade", i["can_upgrade"] is True and i["reason"] is None, i)
    expect("credit = what was paid (1800)", i["current"]["credit"] == 1800, i["current"])
    expect("window ends start + 15", i["current"]["window_ends"] == (start + timedelta(days=15)).isoformat(),
           i["current"])
    opts = {o["plan_id"]: o for o in i["options"]}
    expect("current plan not pickable", opts[one["id"]]["eligible"] is False
           and opts[one["id"]]["reason"] == "Current plan", opts.get(one["id"]))
    expect("lower price shown but not pickable", opts[cheap["id"]]["eligible"] is False
           and "Lower price" in opts[cheap["id"]]["reason"], opts.get(cheap["id"]))
    expect("shorter plan not pickable", opts[short["id"]]["eligible"] is False
           and "Shorter" in opts[short["id"]]["reason"], opts.get(short["id"]))
    expect("3 months pickable, balance 3200", opts[three["id"]]["eligible"] is True
           and opts[three["id"]]["balance"] == 3200, opts.get(three["id"]))
    upgrade(a, cheap, 0, 400)
    upgrade(a, short, 0, 400)
    upgrade(a, three, 9999, 400)                       # paid more than the balance
    done = upgrade(a, three, 3200)
    expect("billed only the balance", done.get("amount") == 3200 and done.get("balance_amount") == 0, done)

    subs = check("history", c.get(f"/api/v1/subscriptions/member/{a['id']}"))["data"]
    new = next(s for s in subs if s["id"] == done["subscription_ids"][0])
    old = next(s for s in subs if s["plan_id"] == one["id"])
    expect("new plan starts on the old start", new["start_date"] == start.isoformat(), new)
    expect("old plan marked upgraded", old["upgraded_to_id"] == new["id"], old)
    expect("new plan records credit + link", new["upgrade_credit"] == 1800 and new["upgraded_from_id"] == old["id"],
           new)
    m = check("member now on 3 months", c.get(f"/api/v1/members/{a['id']}"))["data"]
    expect("current plan is the new one", m.get("current_plan_id") == three["id"], m)
    inv = check("invoice", c.get(f"/api/v1/payments/{done['payment_id']}/invoice"))["data"]
    expect("invoice shows the credit", inv["credit_amount"] == 1800 and one["name"] in (inv["credit_label"] or "")
           and inv["gross"] == 3200, {k: inv[k] for k in ("credit_amount", "credit_label", "gross")})
    upgrade(a, three, 0, 400)                          # same plan again
    i2 = info(a)
    expect("chain: credit is the 3 months price", i2["current"]["credit"] == 5000, i2["current"])
    expect("6 months balance 4000", {o["plan_id"]: o for o in i2["options"]}[six["id"]]["balance"] == 4000, i2)

    print("\n── refusals ──")
    b = member("B")
    enrol(b, one, today - timedelta(days=20), paid=2000)
    ib = info(b)
    expect("window closed", ib["can_upgrade"] is False and "window closed" in (ib["reason"] or ""), ib)
    expect("nothing pickable", not any(o["eligible"] for o in ib["options"]), "")
    upgrade(b, three, 3000, 400)
    cm = member("C")
    enrol(cm, one, today, paid=500)
    ic = info(cm)
    expect("balance pending blocks", ic["can_upgrade"] is False and "Balance" in (ic["reason"] or ""), ic)
    d = member("D")
    enrol(d, off, today, paid=2100)
    id_ = info(d)
    expect("window 0 = upgrades off", id_["can_upgrade"] is False and "off" in (id_["reason"] or ""), id_)
    e = member("E")
    ie = info(e)
    expect("no plan → can't upgrade", ie["can_upgrade"] is False and ie["current"] is None, ie)

    print("\n── cleanup ──")
    for p in (one, three, six, cheap, short, off):
        check(f"deactivate {p['name']}", c.put(f"/api/v1/plans/{p['id']}", json={"is_active": False}))

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
