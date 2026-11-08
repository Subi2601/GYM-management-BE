"""Smoke test: referrals — referred-by links (member + lead), loop guard, monthly reward tiers, eligible list,
give reward, reward history, referral tree colours, permissions.

    python -m scripts.smoke_referrals [base_url]

Works on Main Branch with fresh members. Sets this month's reward (puts back the previous one if there was one).
"""
from __future__ import annotations

import sys
import time
from datetime import date

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
    tok = check("login", c.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    c.headers["Authorization"] = f"Bearer {tok['data']['access_token']}"
    me = check("me", c.get("/api/v1/auth/me"))["data"]
    c.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["Main Branch"]
    gen = next(x["id"] for x in check("categories", c.get("/api/v1/plan-categories"))["data"] if x["name"] == "General")
    today = date.today()
    key = f"{today.year}-{today.month:02d}"
    plan = check("plan", c.post("/api/v1/plans", json={"name": f"Rf 1 Month {RUN}", "category_id": gen,
                                                        "price": 1500, "duration_months": 1}), 201)["data"]

    def member(label: str, referred_by: str | None = None) -> dict:
        body = {"name": f"Rf {label} {RUN}", "phone": phone()}
        if referred_by:
            body["referred_by_id"] = referred_by
        return check(f"member {label}", c.post("/api/v1/members", json=body), 201)["data"]

    def enrol(m: dict) -> None:
        check(f"enrol {m['name']}", c.post("/api/v1/subscriptions/enroll", json={
            "member_id": m["id"], "plan_ids": [plan["id"]], "payment": {"paid_amount": 1500, "payment_mode": "CASH"}}), 201)

    print("\n── monthly reward ──")
    before = check("status", c.get("/api/v1/referrals/status"))["data"]["current"]
    check("past month → 400", c.put("/api/v1/referrals/program", json={
        "month_key": "2020-01", "tiers": [{"min_referrals": 1, "reward": "x"}]}), 400)
    check("duplicate tier → 400", c.put("/api/v1/referrals/program", json={
        "month_key": key, "tiers": [{"min_referrals": 1, "reward": "a"}, {"min_referrals": 1, "reward": "b"}]}), 400)
    prog = check("set this month", c.put("/api/v1/referrals/program", json={
        "month_key": key, "title": "Smoke referral reward", "tiers": [
            {"min_referrals": 2, "reward": "1 month free"}, {"min_referrals": 1, "reward": "Gym T-shirt"}]}))["data"]
    expect("tiers sorted, set", prog["is_set"] and [t["min_referrals"] for t in prog["tiers"]] == [1, 2], prog)

    print("\n── referred-by links ──")
    r = member("Referrer")
    a = member("A", r["id"])
    b = member("B", r["id"])
    cc = member("C", a["id"])
    unpaid = member("Unpaid", r["id"])
    for m in (r, a, b, cc):
        enrol(m)
    expect("referred_by_name on member", a["referred_by_name"] == r["name"], a)
    check("self referral → 400", c.put(f"/api/v1/members/{r['id']}", json={"referred_by_id": r["id"]}), 400)
    check("loop R←C → 400", c.put(f"/api/v1/members/{r['id']}", json={"referred_by_id": cc["id"]}), 400)
    lst = check("member list", c.get("/api/v1/members", params={"search": r["registration_id"]}))["data"]
    expect("referral count 3 (incl. unpaid)", lst[0]["referral_count"] == 3, lst[0])

    lead = check("lead referred by B", c.post("/api/v1/leads", json={
        "name": f"Rf Lead {RUN}", "phone": phone(), "location": "Anna Nagar", "goal": "WEIGHT_LOSS",
        "source": "REFERRAL", "status": "NEW", "plan_to_join_date": today.isoformat(),
        "next_follow_up_date": today.isoformat(), "referred_by_id": b["id"]}), 201)["data"]
    expect("lead shows referrer", lead["referred_by_name"] == b["name"], lead)
    conv = check("convert lead", c.post(f"/api/v1/leads/{lead['id']}/convert"))["data"]
    got = check("converted member", c.get(f"/api/v1/members/{conv['member_id']}"))["data"]
    expect("referrer copied to member", got["referred_by_id"] == b["id"], got)

    print("\n── eligible this month ──")
    el = check("eligible", c.get("/api/v1/referrals/eligible"))["data"]
    rows = {x["member_id"]: x for x in el["rows"]}
    expect("R: 2 paid referrals → 1 month free (unpaid not counted)", rows.get(r["id"], {}).get("referral_count") == 2
           and rows[r["id"]]["reward"] == "1 month free" and rows[r["id"]]["eligible"], rows.get(r["id"]))
    expect("A: 1 → T-shirt, next is 1 month free", rows.get(a["id"], {}).get("reward") == "Gym T-shirt"
           and rows[a["id"]]["next_reward"] == "1 month free" and rows[a["id"]]["needed_for_next"] == 1, rows.get(a["id"]))
    counts = check("counts", c.get("/api/v1/referrals/counts"))["data"]
    expect("eligible count ≥ 2", counts["eligible"] >= 2, counts)

    print("\n── tree ──")
    direct = check("direct referrals R", c.get(f"/api/v1/referrals/tree/{r['id']}"))["data"]
    expect("default = direct only (3, no grandchildren)", direct["total_referred"] == 3
           and all(not k["children"] for k in direct["root"]["children"]), direct["root"])
    dk = {k["member_id"]: k for k in direct["root"]["children"]}
    expect("paid flags + A counted", dk[a["id"]]["paid"] and not dk[unpaid["id"]]["paid"]
           and dk[a["id"]]["counted_status"] == "PENDING" and dk[a["id"]]["referral_count"] == 1, dk[a["id"]])
    tree = check("tree R (all levels)", c.get(f"/api/v1/referrals/tree/{r['id']}", params={"levels": 8}))["data"]
    kids = {k["member_id"]: k for k in tree["root"]["children"]}
    expect("R has A, B, Unpaid; A has C", set(kids) == {a["id"], b["id"], unpaid["id"]}
           and [g["member_id"] for g in kids[a["id"]]["children"]] == [cc["id"]], tree["root"])
    expect("colours: R reward due, A counted, Unpaid not counted", tree["root"]["reward_due"] and kids[a["id"]]["counted"]
           and not kids[unpaid["id"]]["counted"], tree["root"])
    expect("plan shown on nodes", kids[a["id"]]["plan_name"] == plan["name"], kids[a["id"]])
    expect("total referred 5 (A, B, Unpaid, C under A, the converted lead under B)", tree["total_referred"] == 5,
           tree["total_referred"])
    leaf = check("tree of C", c.get(f"/api/v1/referrals/tree/{cc['id']}"))["data"]
    expect("C referred by A, no children", leaf["referred_by"]["member_id"] == a["id"] and not leaf["root"]["children"], leaf)

    print("\n── give ──")
    gave = check("give R", c.post("/api/v1/referrals/give", json={"member_id": r["id"], "note": "Handed at desk"}))
    expect("message names reward", "1 month free" in (gave.get("message") or ""), gave)
    check("give again → 409", c.post("/api/v1/referrals/give", json={"member_id": r["id"]}), 409)
    check("give unpaid (0 referrals) → 400", c.post("/api/v1/referrals/give", json={"member_id": unpaid["id"]}), 400)
    rw = check("rewarded list", c.get("/api/v1/referrals/rewards", params={"status": "GIVEN", "search": r["registration_id"]}))
    row = rw["data"][0] if rw["data"] else {}
    expect("history: reward for A and B", row.get("reward") == "1 month free"
           and {p["member_id"] for p in row.get("referred", [])} == {a["id"], b["id"]}, row)
    tree = check("tree R again", c.get(f"/api/v1/referrals/tree/{r['id']}"))["data"]
    expect("A now counted for a GIVEN reward", {k["member_id"]: k for k in tree["root"]["children"]}[a["id"]]
           ["counted_status"] == "GIVEN", tree["root"]["children"])
    expect("R now rewarded, history on tree", tree["root"]["rewarded"] and not tree["root"]["reward_due"]
           and tree["rewards"][0]["status"] == "GIVEN", tree["root"])

    print("\n── permissions ──")
    staff = httpx.Client(base_url=BASE, timeout=30)
    st = check("staff login", staff.post("/api/v1/auth/login", json={"email": "trainer@gym.com", "password": "trainer123"}))
    staff.headers["Authorization"] = f"Bearer {st['data']['access_token']}"
    check("staff sees status", staff.get("/api/v1/referrals/status"))
    check("staff can't set reward", staff.put("/api/v1/referrals/program", json={
        "month_key": key, "tiers": [{"min_referrals": 1, "reward": "x"}]}), 403)

    print("\n── cleanup ──")
    if before["is_set"]:
        check("put previous reward back", c.put("/api/v1/referrals/program", json={
            "month_key": key, "title": before["title"], "notes": before["notes"], "tiers": before["tiers"]}))
    c.put(f"/api/v1/plans/{plan['id']}", json={"is_active": False})

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
