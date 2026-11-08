"""Smoke test: Gym settings (trial, renewal days, late grace) + trial class from Leads and the enquiry form.

    python -m scripts.smoke_trial_settings [base_url]

Runs on North Branch with fresh phone numbers, puts the gym settings back as they were and deletes the leads it
made. Regenerates nothing.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
failures = 0
_seq = int(time.time() * 10) % 10**8
_used: list[str] = []


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
    _used.append(f"6{_seq % 10**9:09d}")
    return _used[-1]


def login(email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=30)
    tok = check(f"login {email}", c.post("/api/v1/auth/login", json={"email": email, "password": password}))
    c.headers["Authorization"] = f"Bearer {tok['data']['access_token']}"
    return c


def main() -> None:
    owner = login("owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    owner.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["North Branch"]
    public = httpx.Client(base_url=BASE, timeout=30)
    today = date.today()

    print("\n── settings ──")
    before = check("get settings", owner.get("/api/v1/settings"))["data"]
    check("trial days 0 → 422", owner.put("/api/v1/settings", json={"trial_days": 0}), 422)
    check("negative fee → 422", owner.put("/api/v1/settings", json={"trial_fee": -1}), 422)
    saved = check("save 5 days / ₹199 / renewals 10 + 45 / grace 15", owner.put("/api/v1/settings", json={
        "trial_enabled": True, "trial_days": 5, "trial_fee": 199, "renewal_due_days": 10,
        "renewal_overdue_days": 45, "late_grace_minutes": 15}))["data"]
    expect("saved values", saved["trial_days"] == 5 and saved["trial_fee"] == 199
           and saved["renewal_due_days"] == 10 and saved["late_grace_minutes"] == 15, saved)
    desk = check("desk settings", owner.get("/api/v1/settings/desk"))["data"]
    expect("desk values match", {k: desk[k] for k in ("trial_enabled", "trial_days", "trial_fee", "renewal_due_days",
                                                      "renewal_overdue_days")}
           == {"trial_enabled": True, "trial_days": 5, "trial_fee": 199.0, "renewal_due_days": 10,
               "renewal_overdue_days": 45} and desk["gym_code"], desk)
    r10 = check("renewal counts (gym default)", owner.get("/api/v1/renewals/counts"))["data"]
    r10x = check("renewal counts within=10", owner.get("/api/v1/renewals/counts", params={"within": 10}))["data"]
    expect("no window sent = gym's 10 days", r10 == r10x, (r10, r10x))

    print("\n── trial from Leads ──")
    p = phone()
    lead = check("add lead", owner.post("/api/v1/leads", json={
        "name": "Trial Walkin", "phone": p, "location": "Anna Nagar", "goal": "WEIGHT_LOSS", "source": "WALK_IN",
        "status": "NEW", "plan_to_join_date": str(today + timedelta(days=7)),
        "next_follow_up_date": str(today)}), 201)["data"]
    lid = lead["id"]
    check("start too far ahead → 400", owner.post(f"/api/v1/leads/{lid}/trial",
                                                   json={"start_date": str(today + timedelta(days=40))}), 400)
    t = check("start trial today", owner.post(f"/api/v1/leads/{lid}/trial", json={"start_date": str(today)}))["data"]
    expect("5-day trial, ₹199, ON", t["trial_start"] == str(today) and t["trial_end"] == str(today + timedelta(days=4))
           and t["trial_fee"] == 199 and t["trial_state"] == "ON", t)
    expect("follow-up on the last trial day", t["next_follow_up_date"] == t["trial_end"], t)
    check("second trial → 409", owner.post(f"/api/v1/leads/{lid}/trial", json={"start_date": str(today)}), 409)
    check("visit before paying → 400", owner.post(f"/api/v1/leads/{lid}/trial/visit"), 400)
    t = check("mark paid (UPI)", owner.post(f"/api/v1/leads/{lid}/trial/paid", json={"payment_mode": "UPI"}))["data"]
    expect("paid today", t["trial_paid_on"] == str(today) and t["trial_payment_mode"] == "UPI", t)
    check("pay twice → 409", owner.post(f"/api/v1/leads/{lid}/trial/paid", json={"payment_mode": "CASH"}), 409)
    t = check("visit 1", owner.post(f"/api/v1/leads/{lid}/trial/visit"))["data"]
    expect("1 visit", t["trial_visits"] == 1 and t["trial_last_visit"] == str(today), t)
    check("visit twice today → 409", owner.post(f"/api/v1/leads/{lid}/trial/visit"), 409)
    check("cancel after visit → 400", owner.delete(f"/api/v1/leads/{lid}/trial"), 400)
    counts = check("lead counts", owner.get("/api/v1/leads/counts"))["data"]
    on_tab = check("trial tab", owner.get("/api/v1/leads", params={"filter": "trial", "search": p}))
    expect("on the trial tab", counts["trial"] >= 1 and on_tab["total"] == 1, (counts, on_tab))

    p2 = phone()
    l2 = check("lead for cancel", owner.post("/api/v1/leads", json={
        "name": "Trial Later", "phone": p2, "location": "KK Nagar", "goal": "MUSCLE_GAIN", "source": "PHONE_CALL",
        "status": "NEW", "plan_to_join_date": str(today + timedelta(days=7)),
        "next_follow_up_date": str(today)}), 201)["data"]
    t = check("book for next week", owner.post(f"/api/v1/leads/{l2['id']}/trial",
                                               json={"start_date": str(today + timedelta(days=7))}))["data"]
    expect("UPCOMING", t["trial_state"] == "UPCOMING", t)
    check("visit before start → 400", owner.post(f"/api/v1/leads/{l2['id']}/trial/visit"), 400)
    t = check("cancel", owner.delete(f"/api/v1/leads/{l2['id']}/trial"))["data"]
    expect("trial cleared", t["trial_start"] is None and t["trial_state"] is None, t)

    print("\n── trial from the enquiry form ──")
    token = check("form link", owner.get("/api/v1/leads/enquiry-form"))["data"]["token"]
    info = check("form info", public.get(f"/api/v1/public/enquiry/{token}"))["data"]
    expect("form shows the offer", info["trial_enabled"] and info["trial_days"] == 5 and info["trial_fee"] == 199
           and info["trial_book_ahead_days"] == 14, info)

    def submit(body: dict, status: int = 201) -> dict:
        return check(f"submit {body.get('name')}", public.post(
            f"/api/v1/public/enquiry/{token}", json=body,
            headers={"X-Forwarded-For": f"10.8.{_seq % 250}.{time.time_ns() % 250}"}), status)

    submit({"name": "No Date", "phone": phone(), "trial": True}, 400)
    submit({"name": "Far Date", "phone": phone(), "trial": True, "trial_date": str(today + timedelta(days=20))}, 400)
    fp = phone()
    r = submit({"name": "Form Trial", "phone": fp, "trial": True, "trial_date": str(today + timedelta(days=1))})
    expect("thank-you with trial dates", r["data"]["trial_start"] == str(today + timedelta(days=1))
           and r["data"]["trial_end"] == str(today + timedelta(days=5)) and "trial" in r["message"].lower(), r)
    found = check("find form lead", owner.get("/api/v1/leads", params={"search": fp}))["data"][0]
    expect("lead has the trial, follow-up today", found["trial_start"] == str(today + timedelta(days=1))
           and found["next_follow_up_date"] == str(today) and found["source"] == "ENQUIRY_FORM", found)
    r = submit({"name": "Form Trial", "phone": fp, "trial": True, "trial_date": str(today)})
    expect("second trial refused politely", r["data"]["trial_used"] is True and r["data"]["trial_start"] is None, r)

    print("\n── trial switched off ──")
    check("switch trials off", owner.put("/api/v1/settings", json={"trial_enabled": False}))
    info = check("form info", public.get(f"/api/v1/public/enquiry/{token}"))["data"]
    expect("form hides the offer", not info["trial_enabled"] and info["trial_days"] == 0, info)
    submit({"name": "Off Trial", "phone": phone(), "trial": True, "trial_date": str(today)}, 400)
    p3 = phone()
    l3 = check("lead", owner.post("/api/v1/leads", json={
        "name": "Trial Off", "phone": p3, "location": "Vadapalani", "goal": "GENERAL_FITNESS", "source": "WALK_IN",
        "status": "NEW", "plan_to_join_date": str(today), "next_follow_up_date": str(today)}), 201)["data"]
    check("start trial when off → 400", owner.post(f"/api/v1/leads/{l3['id']}/trial", json={"start_date": str(today)}),
          400)

    print("\n── permissions ──")
    staff = login("trainer@gym.com", "trainer123")
    check("staff can't open settings", staff.get("/api/v1/settings"), 403)
    check("staff sees the desk settings", staff.get("/api/v1/settings/desk"))

    print("\n── cleanup ──")
    restore = {k: before[k] for k in ("trial_enabled", "trial_days", "trial_fee", "renewal_due_days",
                                      "renewal_overdue_days", "late_grace_minutes")}
    check("settings back", owner.put("/api/v1/settings", json=restore))
    removed = 0
    for num in _used:
        for row in owner.get("/api/v1/leads", params={"search": num}).json().get("data") or []:
            removed += owner.delete(f"/api/v1/leads/{row['id']}").status_code == 200
    print(f"deleted {removed} test lead(s)")

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
