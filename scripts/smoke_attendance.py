"""End-to-end smoke test for attendance sessions + QR check-in against a running server.

    python -m scripts.smoke_attendance [base_url]

Runs in North Branch: sets a gym location, links three "phones" (separate cookie jars) to a staff member, an
active member and a member without a plan, scans in / out, checks the front-desk paths, rate limit, linked phones
and QR regeneration, then clears the location and terminates the test staff member.
"""
from __future__ import annotations

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
GYM = {"latitude": 13.0827, "longitude": 80.2707}
FAR = {"latitude": 13.1827, "longitude": 80.2707}         # ~11 km north
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
    return f"7{_seq % 10**9:09d}"


def id_number(code: str) -> str:
    return code.rsplit("-", 1)[1]


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=30)
    token = check("login", owner.post("/api/v1/auth/login",
                                      json={"email": "owner@gym.com", "password": "owner123"}))["data"]["access_token"]
    owner.headers["Authorization"] = f"Bearer {token}"
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    north = next(b for b in me["branches"] if b["branch_name"] == "North Branch")
    owner.headers["X-Branch-ID"] = north["id"]

    # ── admin: posters + location ──
    qr = check("qr settings", owner.get("/api/v1/attendance/qr"))["data"]
    expect("qr token exists", len(qr["checkin_token"]) >= 16, qr)
    check("location: only one coordinate → 400", owner.put("/api/v1/attendance/qr/location",
                                                          json={"latitude": 13.08, "geofence_m": 150}), 400)
    check("location: radius too small → 422", owner.put("/api/v1/attendance/qr/location",
                                                       json={**GYM, "geofence_m": 10}), 422)
    check("set gym location", owner.put("/api/v1/attendance/qr/location", json={**GYM, "geofence_m": 150}))
    url = f"/api/v1/public/checkin/{qr['checkin_token']}"

    # ── people ──
    staff_phone = phone()
    staff = check("create staff", owner.post("/api/v1/employees", json={
        "name": "QR Smoke Staff", "phone": staff_phone, "email": "qr@example.com", "address": "1 Gym Road",
        "role": "TRAINER", "date_of_joining": "2025-01-01", "morning_start": "00:01", "morning_end": "23:50",
        "evening_start": "23:55", "evening_end": "23:59"}), 201)["data"]
    plans = check("plans", owner.get("/api/v1/plans", params={"page_size": 100}))["data"]
    monthly = next(p for p in plans if p["type"] == "MEMBERSHIP")
    active_phone, noplan_phone = phone(), phone()
    active = check("create active member", owner.post("/api/v1/members",
                                                       json={"name": "QR Active Member", "phone": active_phone}), 201)["data"]
    check("enrol active member", owner.post("/api/v1/subscriptions/enroll", json={
        "member_id": active["id"], "plan_ids": [monthly["id"]], "payment": {"paid_amount": 0, "payment_mode": "CASH"}}), 201)
    noplan = check("create member without plan", owner.post("/api/v1/members",
                                                            json={"name": "QR No Plan", "phone": noplan_phone}), 201)["data"]

    # ── phone 1: staff ──
    p1 = httpx.Client(base_url=BASE, timeout=30)
    info = check("public info (not linked)", p1.get(url))["data"]
    expect("info: location required, no person", info["location_required"] and info["person"] is None, info)
    check("bad token → 404", p1.get("/api/v1/public/checkin/notarealtoken000000"), 404)
    check("verify wrong ID → 400", p1.post(f"{url}/verify", json={"phone": staff_phone, "id_number": "99999"}), 400)
    check("scan before linking → 400", p1.post(f"{url}/scan", json={"direction": "in", **GYM}), 400)
    linked = check("verify staff", p1.post(f"{url}/verify", json={"phone": staff_phone,
                                                                   "id_number": id_number(staff["employee_code"])}))
    expect("verify names the staff", linked["data"]["name"] == "QR Smoke Staff", linked)
    expect("device cookie set", "stag_device" in p1.cookies, dict(p1.cookies))
    info = check("public info (linked)", p1.get(url))["data"]
    expect("info shows linked person", (info["person"] or {}).get("person_type") == "STAFF", info)
    check("scan without location → 400", p1.post(f"{url}/scan", json={"direction": "in"}), 400)
    far = check("scan far away → 400", p1.post(f"{url}/scan", json={"direction": "in", **FAR}), 400)
    expect("far message gives distance", "m from North Branch" in far.get("message", ""), far)
    inn = check("staff scan IN", p1.post(f"{url}/scan", json={"direction": "in", **GYM, "accuracy": 30}))
    expect("IN result", inn["data"]["direction"] == "IN" and "checked in" in inn["message"], inn)
    check("staff scan IN again → 400", p1.post(f"{url}/scan", json={"direction": "in", **GYM}), 400)
    out = check("staff scan OUT", p1.post(f"{url}/scan", json={"direction": "out", **GYM}))
    expect("OUT has duration", out["data"]["duration_minutes"] is not None, out)
    check("staff scan OUT again → 400", p1.post(f"{url}/scan", json={"direction": "out", **GYM}), 400)
    daily = check("staff daily", owner.get("/api/v1/attendance/daily"))["data"]
    row = next((r for r in daily["records"] if r["employee_id"] == staff["id"]), None)
    expect("staff day row from QR", row is not None and row["source"] == "QR" and row["visits"] == 1
           and row["check_out_time"] is not None and not row["inside"], row)
    # Status depends on the time the test runs vs the shift (late grace / half day from Gym settings).
    expect("staff marked present / late / half day", row is not None
           and row["status"] in ("PRESENT", "LATE", "HALF_DAY"), row)
    check("staff scan IN (2nd visit)", p1.post(f"{url}/scan", json={"direction": "in", **GYM}))
    row = next(r for r in check("staff daily again", owner.get("/api/v1/attendance/daily"))["data"]["records"]
               if r["employee_id"] == staff["id"])
    expect("2 visits, inside, out cleared", row["visits"] == 2 and row["inside"] and row["check_out_time"] is None, row)
    check("front desk checkout staff", owner.post(f"/api/v1/attendance/{staff['id']}/checkout"))

    # ── phone 2: active member ──
    p2 = httpx.Client(base_url=BASE, timeout=30)
    check("verify member (full code)", p2.post(f"{url}/verify", json={"phone": active_phone,
                                                                       "id_number": active["registration_id"]}))
    check("member scan IN", p2.post(f"{url}/scan", json={"direction": "in", **GYM}))
    check("phone 2 can't re-link to staff → 400", p2.post(f"{url}/verify", json={
        "phone": staff_phone, "id_number": id_number(staff["employee_code"])}), 400)
    check("manual check-in while inside → 400", owner.post("/api/v1/attendance/members/check-in",
                                                           json={"member_id": active["id"]}), 400)
    out = check("manual member check-out", owner.post(f"/api/v1/attendance/members/{active['id']}/check-out"))
    expect("check-out toast text", "checked out at" in out.get("message", ""), out)
    check("manual member check-in", owner.post("/api/v1/attendance/members/check-in", json={"member_id": active["id"]}))

    # ── phone 3: member without a plan ──
    p3 = httpx.Client(base_url=BASE, timeout=30)
    check("verify no-plan member", p3.post(f"{url}/verify", json={"phone": noplan_phone,
                                                                   "id_number": id_number(noplan["registration_id"])}))
    denied = check("no-plan scan IN → 400", p3.post(f"{url}/scan", json={"direction": "in", **GYM}), 400)
    expect("denied message", "No active membership" in denied.get("message", ""), denied)
    check("manual check-in without plan → 400", owner.post("/api/v1/attendance/members/check-in",
                                                           json={"member_id": noplan["id"]}), 400)

    members = check("members daily", owner.get("/api/v1/attendance/members/daily"))["data"]
    mine = [r for r in members["records"] if r["member_id"] == active["id"]]
    expect("active member: 2 visits, 1 open", len(mine) == 2 and sum(r["check_out_time"] is None for r in mine) == 1, mine)
    expect("sources QR + MANUAL", {r["in_source"] for r in mine} == {"QR", "MANUAL"}, mine)
    refused = [r for r in members["records"] if r["member_id"] == noplan["id"]]
    expect("refused check-in logged", len(refused) == 1 and refused[0]["denied_reason"] == "No active membership", refused)
    expect("summary counts", members["summary"]["denied"] >= 1 and members["summary"]["inside"] >= 1, members["summary"])
    open_visit = next(r for r in mine if r["check_out_time"] is None)
    check("close visit in the future → 400", owner.post(f"/api/v1/attendance/sessions/{open_visit['id']}/check-out",
                                                        json={"check_out_time": "23:59:59"}), 400 if time.localtime().tm_hour < 23 else 200)
    check("close visit now", owner.post(f"/api/v1/attendance/sessions/{open_visit['id']}/check-out", json={}))
    check("close it again → 400", owner.post(f"/api/v1/attendance/sessions/{open_visit['id']}/check-out", json={}), 400)
    check("close refused row → 400", owner.post(f"/api/v1/attendance/sessions/{refused[0]['id']}/check-out", json={}), 400)

    # ── rate limit: 5 wrong ID numbers for one phone number, then 429 ──
    p4 = httpx.Client(base_url=BASE, timeout=30)
    target = phone()
    for i in range(5):
        p4.post(f"{url}/verify", json={"phone": target, "id_number": str(900 + i)})
    check("6th wrong attempt → 429", p4.post(f"{url}/verify", json={"phone": target, "id_number": "1"}), 429)

    # ── linked phones + regenerate ──
    devices = check("linked phones", owner.get("/api/v1/attendance/qr/devices"))["data"]
    codes = {staff["employee_code"], active["registration_id"], noplan["registration_id"]}
    ours = [d for d in devices if d["person_code"] in codes]
    expect("3 phones linked", len(ours) == 3, ours)
    staff_device = next(d for d in ours if d["person_type"] == "STAFF")
    check("unlink staff phone", owner.delete(f"/api/v1/attendance/qr/devices/{staff_device['id']}"))
    info = check("phone 1 after unlink", p1.get(url))["data"]
    expect("phone 1 no longer linked", info["person"] is None, info)
    new = check("regenerate QR", owner.post("/api/v1/attendance/qr/regenerate"))["data"]
    expect("token changed", new["checkin_token"] != qr["checkin_token"])
    check("old poster → 404", p2.get(url), 404)
    check("new poster works", p2.get(f"/api/v1/public/checkin/{new['checkin_token']}"))

    # ── cleanup ──
    check("clear gym location", owner.put("/api/v1/attendance/qr/location",
                                          json={"latitude": None, "longitude": None, "geofence_m": 150}))
    check("terminate test staff", owner.patch(f"/api/v1/employees/{staff['id']}/terminate"))
    print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
