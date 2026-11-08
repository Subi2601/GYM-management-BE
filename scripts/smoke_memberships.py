"""Smoke test: membership actions (freeze, transfer, cancel & refund), offer bonuses, "Not coming" list,
client assessments, Gym ID / member id prefix.

    python -m scripts.smoke_memberships [base_url]

Works on Main Branch with its own plans / offer (made inactive at the end) and fresh members every run. Gym
settings are changed for the run and put back at the end.
"""
from __future__ import annotations

import base64
import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
RUN = int(time.time()) % 10**7
failures = 0
_seq = int(time.time() * 10) % 10**8
PDF = base64.b64encode(b"%PDF-1.4\n% smoke proof\n").decode()


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


def iso(d: date) -> str:
    return d.isoformat()


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    token = check("login", c.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    c.headers["Authorization"] = f"Bearer {token['data']['access_token']}"
    me = check("me", c.get("/api/v1/auth/me"))["data"]
    c.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["Main Branch"]
    gen = next(x["id"] for x in check("categories", c.get("/api/v1/plan-categories"))["data"] if x["name"] == "General")
    today = date.today()
    before = check("settings", c.get("/api/v1/settings"))["data"]
    check("set test limits", c.put("/api/v1/settings", json={
        "freeze_enabled": True, "freeze_max_days": 20, "freeze_max_times": 2, "transfer_enabled": True,
        "transfer_within_days": 15, "refund_within_days": 7, "refund_deduction_percent": 10,
        "absent_alert_days": 7}))
    made_plans: list[str] = []

    def plan(name: str, price: float, **extra) -> dict:
        p = check(f"plan {name}", c.post("/api/v1/plans", json={
            "name": f"Mb {name} {RUN}", "category_id": gen, "price": price, "duration_months": 1, **extra}), 201)["data"]
        made_plans.append(p["id"])
        return p

    def member(label: str) -> dict:
        return check(f"member {label}", c.post("/api/v1/members", json={"name": f"Mb {label} {RUN}",
                                                                         "phone": phone()}), 201)["data"]

    def enrol(m: dict, p: dict, start: date, paid: float, offer_id: str | None = None) -> dict:
        pay = {"paid_amount": paid, "payment_mode": "CASH"}
        if offer_id:
            pay["offer_id"] = offer_id
        return check(f"enrol {m['name']}", c.post("/api/v1/subscriptions/enroll", json={
            "member_id": m["id"], "plan_ids": [p["id"]], "start_date": iso(start), "payment": pay}), 201)["data"]

    def actions(m: dict) -> dict:
        return check(f"actions {m['name']}", c.get(f"/api/v1/memberships/member/{m['id']}"))["data"]

    print("\n── Gym ID / member id ──")
    s = check("settings", c.get("/api/v1/settings"))["data"]
    expect("gym code + SG prefix", s["gym_code"] == "STAG" and s["member_id_prefix"] == "SG", s)
    m0 = member("Prefix")
    expect("member id SG-###", m0["registration_id"].startswith("SG-"), m0)

    print("\n── plans ──")
    plain = plan("1 Month", 2000)
    refundable = plan("1 Month Refund", 2000, refundable=True)
    refund3 = plan("1 Month Refund 3d", 2000, refundable=True, refund_window_days=3)
    expect("refund flags saved", refundable["refundable"] is True and refundable["refund_window_days"] is None
           and refund3["refund_window_days"] == 3 and plain["refundable"] is False, (refundable, refund3))

    print("\n── freeze ──")
    a = member("Freeze")
    start = today - timedelta(days=3)
    enrol(a, plain, start, 2000)
    info = actions(a)
    sub_id = info["current"]["subscription_id"]
    end0 = date.fromisoformat(info["current"]["end_date"])
    expect("freeze allowed, 20 days", info["freeze"]["allowed"] and info["freeze"]["allowance_days"] == 20, info["freeze"])
    check("no reason → 422", c.post(f"/api/v1/memberships/{sub_id}/freeze",
                                    json={"start_date": iso(today), "days": 5, "reason": ""}), 422)
    check("too many days → 400", c.post(f"/api/v1/memberships/{sub_id}/freeze",
                                        json={"start_date": iso(today), "days": 25, "reason": "Travel"}), 400)
    r = check("freeze 10 days + proof", c.post(f"/api/v1/memberships/{sub_id}/freeze", json={
        "start_date": iso(today), "days": 10, "reason": "Accident, doctor advised rest",
        "document": {"file_name": "doctor-note.pdf", "content_type": "application/pdf", "data_base64": PDF}}))
    expect("freeze message", "frozen" in (r.get("message") or ""), r)
    info = actions(a)
    expect("end +10 days, 10 used", date.fromisoformat(info["current"]["end_date"]) == end0 + timedelta(days=10)
           and info["freeze"]["used_days"] == 10 and info["freeze"]["active"] is not None, info)
    expect("second freeze blocked while frozen", info["freeze"]["allowed"] is False, info["freeze"])
    docs = check("documents", c.get(f"/api/v1/memberships/member/{a['id']}/documents"))["data"]
    expect("proof stored", len(docs) == 1 and docs[0]["kind"] == "FREEZE", docs)
    dl = c.get(f"/api/v1/memberships/documents/{docs[0]['id']}")
    expect("proof downloads", dl.status_code == 200 and dl.content.startswith(b"%PDF"), dl.status_code)
    ci = check("check-in while frozen → 400", c.post("/api/v1/attendance/members/check-in",
                                                      json={"member_id": a["id"]}), 400)
    expect("frozen message", "frozen" in str(ci).lower(), ci)
    fid = info["freeze"]["active"]["id"]
    check("resume today", c.post(f"/api/v1/memberships/freezes/{fid}/resume"))
    info = actions(a)
    expect("unused days back (all 10, started today)", date.fromisoformat(info["current"]["end_date"]) == end0
           and info["freeze"]["used_days"] == 0, info)
    check("custom allowance 0 → only individual", c.put("/api/v1/settings", json={"freeze_max_days": 0}))
    info = actions(a)
    expect("gym 0 days → not allowed", info["freeze"]["allowed"] is False, info["freeze"])
    check("give member 5 days", c.put(f"/api/v1/memberships/{sub_id}/freeze-allowance", json={"days": 5}))
    info = actions(a)
    expect("member's own 5 days", info["freeze"]["allowed"] and info["freeze"]["allowance_days"] == 5
           and info["freeze"]["custom_allowance"], info["freeze"])
    check("6 days > own allowance → 400", c.post(f"/api/v1/memberships/{sub_id}/freeze", json={
        "start_date": iso(today), "days": 6, "reason": "Pregnancy"}), 400)
    check("backdated freeze 4 days", c.post(f"/api/v1/memberships/{sub_id}/freeze", json={
        "start_date": iso(today - timedelta(days=3)), "days": 4, "reason": "Fever since Monday"}))
    check("put gym freeze days back to 20", c.put("/api/v1/settings", json={"freeze_max_days": 20}))

    print("\n── transfer ──")
    b = member("Giver")
    enrol(b, plain, today - timedelta(days=5), 2000)
    info = actions(b)
    expect("transfer allowed (5 used ≤ 15)", info["transfer"]["allowed"], info["transfer"])
    left = info["transfer"]["remaining_days"]
    bsub = info["current"]["subscription_id"]
    t = check("transfer to new person", c.post(f"/api/v1/memberships/{bsub}/transfer", json={
        "name": f"Mb Receiver {RUN}", "phone": phone(), "reason": "Moving to Bangalore, gives to brother"}))["data"]
    recv = t["new_member_id"]
    rinfo = check("receiver actions", c.get(f"/api/v1/memberships/member/{recv}"))["data"]
    expect("receiver gets the remaining days from today", rinfo["current"]["start_date"] == iso(today)
           and (date.fromisoformat(rinfo["current"]["end_date"]) - today).days + 1 == left
           and rinfo["current"]["received_by_transfer"], rinfo["current"])
    expect("received membership can't move again", rinfo["transfer"]["allowed"] is False
           and "only once" in rinfo["transfer"]["reason"], rinfo["transfer"])
    hist = check("giver history", c.get(f"/api/v1/subscriptions/member/{b['id']}"))["data"]
    expect("giver closed as TRANSFERRED", hist[0]["closed_reason"] == "TRANSFERRED"
           and "Transferred to" in hist[0]["close_note"], hist[0])
    rh = check("receiver history", c.get(f"/api/v1/subscriptions/member/{recv}"))["data"]
    expect("receiver shows paid", rh[0]["payment_status"] == "PAID" and rh[0]["transferred_from_id"] == bsub, rh[0])
    old = member("Too Late")
    enrol(old, plain, today - timedelta(days=20), 2000)
    expect("transfer window closed after 20 days", actions(old)["transfer"]["allowed"] is False, "")
    fz = member("Frozen Early")
    enrol(fz, plain, today - timedelta(days=20), 2000)
    fzi = actions(fz)
    check("freeze from day 2 (emergency)", c.post(f"/api/v1/memberships/{fzi['current']['subscription_id']}/freeze", json={
        "start_date": iso(today - timedelta(days=18)), "days": 19, "reason": "Pregnancy"}))
    fzi = actions(fz)
    expect("frozen member still transferable (used 2 days)", fzi["transfer"]["allowed"]
           and fzi["transfer"]["used_days"] == 2, fzi["transfer"])

    print("\n── cancel & refund ──")
    d = member("Refund")
    enrol(d, refundable, today - timedelta(days=2), 2000)
    di = actions(d)
    expect("refund eligible, suggest 1800", di["cancel"]["refund_eligible"] and di["cancel"]["paid_amount"] == 2000
           and di["cancel"]["suggested_refund"] == 1800, di["cancel"])
    dsub = di["current"]["subscription_id"]
    check("bank refund without IFSC → 422", c.post(f"/api/v1/memberships/{dsub}/cancel", json={
        "reason": "Job transfer", "refund": {"amount": 1800, "mode": "BANK_TRANSFER", "account_holder": "Mb",
                                             "account_number": "123456789012"}}), 422)
    check("refund above paid → 400", c.post(f"/api/v1/memberships/{dsub}/cancel", json={
        "reason": "Job transfer", "refund": {"amount": 2500, "mode": "CASH"}}), 400)
    res = check("cancel with bank refund", c.post(f"/api/v1/memberships/{dsub}/cancel", json={
        "reason": "Job transfer to Pune", "refund": {
            "amount": 1800, "mode": "BANK_TRANSFER", "account_holder": "Mb Refund", "account_number": "123456789012",
            "ifsc": "sbin0001234", "bank_name": "SBI"}}))["data"]
    rf = res["refund"]
    expect("refund RF-, deduction 200, IFSC upper", rf["refund_no"].startswith("RF-") and rf["amount"] == 1800
           and rf["deduction_amount"] == 200 and rf["ifsc"] == "SBIN0001234", rf)
    expect("member now has no running membership", actions(d)["current"] is None, "")
    check("cancel again → 404/400", c.post(f"/api/v1/memberships/{dsub}/cancel", json={"reason": "again"}), 400)
    stats = check("payment stats", c.get("/api/v1/payments/stats"))["data"]
    expect("refund in today's stats", stats["refunds_today"] >= 1800, stats)
    refunds = check("refunds list", c.get("/api/v1/refunds", params={"search": rf["refund_no"]}))
    expect("refund listed", refunds["total"] == 1 and refunds["data"][0]["amount"] == 1800, refunds)
    e = member("No Refund")
    enrol(e, plain, today, 2000)
    ei = actions(e)
    expect("plain plan: no refund", not ei["cancel"]["refund_eligible"] and "isn't refundable" in ei["cancel"]["refund_reason"],
           ei["cancel"])
    check("refund on non-refundable → 400", c.post(f"/api/v1/memberships/{ei['current']['subscription_id']}/cancel",
                                                   json={"reason": "Not happy", "refund": {"amount": 100, "mode": "CASH"}}), 400)
    check("cancel without refund", c.post(f"/api/v1/memberships/{ei['current']['subscription_id']}/cancel",
                                          json={"reason": "Not happy with timings"}))
    f = member("Window 3d")
    enrol(f, refund3, today - timedelta(days=5), 2000)
    fi = actions(f)
    expect("plan's own 3-day window closed", not fi["cancel"]["refund_eligible"]
           and fi["cancel"]["refund_window_days"] == 3, fi["cancel"])

    print("\n── offer bonus ──")
    offer = check("offer +1 month + shaker", c.post("/api/v1/offers", json={
        "name": f"Mb Bonus {RUN}", "discount_percent": 0, "extra_months": 1, "free_item": "Protein shaker"}), 201)["data"]
    expect("summary", offer["summary"] == "+1 month · Free Protein shaker", offer)
    check("empty offer → 422", c.post("/api/v1/offers", json={"name": f"Mb Empty {RUN}", "discount_percent": 0}), 422)
    g = member("Bonus")
    pay = enrol(g, plain, today, 2000, offer_id=offer["id"])
    gh = check("bonus history", c.get(f"/api/v1/subscriptions/member/{g['id']}"))["data"][0]
    expect("2 months instead of 1", date.fromisoformat(gh["end_date"]) > today + timedelta(days=56), gh)
    inv = check("invoice", c.get(f"/api/v1/payments/{pay['payment_id']}/invoice"))["data"]
    expect("invoice shows bonus + gym id", "Protein shaker" in (inv.get("offer_bonus") or "")
           and inv.get("gym_code") == "STAG", inv)
    check("offer off", c.patch(f"/api/v1/offers/{offer['id']}/status", json={"is_active": False}))

    print("\n── not coming ──")
    h = member("Absent")
    enrol(h, plain, today - timedelta(days=10), 2000)
    absent = check("absent tab", c.get("/api/v1/members", params={"filter": "absent", "search": h["registration_id"]}))
    expect("joined 10 days ago, never came → listed", absent["total"] == 1
           and absent["data"][0]["last_visit_date"] is None, absent)
    check("check in today", c.post("/api/v1/attendance/members/check-in", json={"member_id": h["id"]}))
    absent = check("absent tab again", c.get("/api/v1/members", params={"filter": "absent", "search": h["registration_id"]}))
    expect("came today → gone", absent["total"] == 0, absent)
    counts = check("member counts", c.get("/api/v1/members/counts"))["data"]
    expect("absent count present", "absent" in counts, counts)

    print("\n── assessment ──")
    check("BP half → 422", c.post(f"/api/v1/assessments/member/{h['id']}", json={
        "assessed_on": iso(today), "bp_systolic": 120}), 422)
    asm = check("assessment", c.post(f"/api/v1/assessments/member/{h['id']}", json={
        "assessed_on": iso(today), "height_cm": 170, "weight_kg": 72.5, "resting_heart_rate": 72,
        "bp_systolic": 120, "bp_diastolic": 80, "lifestyle": "SEDENTARY", "past_injuries": "Left knee ACL 2019",
        "movements": {"OVERHEAD_SQUAT": "FAIR", "LUNGE": "GOOD"}, "static_notes": "Rounded shoulders"}), 201)["data"]
    expect("BMI 25.1, assessed by owner", asm["bmi"] == 25.1 and asm["assessed_by_name"], asm)
    prof = check("member profile", c.get(f"/api/v1/members/{h['id']}"))["data"]
    expect("profile weight synced", prof["weight"] == 72.5 and prof["height"] == 170, prof)
    lst = check("assessment list", c.get(f"/api/v1/assessments/member/{h['id']}"))["data"]
    expect("one assessment", len(lst) == 1 and lst[0]["movements"]["LUNGE"] == "GOOD", lst)

    print("\n── permissions ──")
    staff = httpx.Client(base_url=BASE, timeout=30)
    st = check("staff login", staff.post("/api/v1/auth/login", json={"email": "trainer@gym.com", "password": "trainer123"}))
    staff.headers["Authorization"] = f"Bearer {st['data']['access_token']}"
    check("staff can't freeze", staff.post(f"/api/v1/memberships/{sub_id}/freeze", json={
        "start_date": iso(today), "days": 1, "reason": "test"}), 403)

    print("\n── cleanup ──")
    check("settings back", c.put("/api/v1/settings", json={k: before[k] for k in (
        "freeze_enabled", "freeze_max_days", "freeze_max_times", "transfer_enabled", "transfer_within_days",
        "refund_within_days", "refund_deduction_percent", "absent_alert_days")}))
    for pid in made_plans:
        c.put(f"/api/v1/plans/{pid}", json={"is_active": False})

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
