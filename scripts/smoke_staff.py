"""End-to-end smoke test for the Staff module (employees, attendance, payroll) against a running server.

    python -m scripts.smoke_staff [base_url]

Re-runnable: every run creates fresh employees (unique phones) in North Branch and terminates them at the end.
Salary checks use February 2025 (28 days) so the numbers are exact.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
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


def login(client: httpx.Client, email: str, password: str) -> None:
    body = check(f"login {email}", client.post("/api/v1/auth/login", json={"email": email, "password": password}))
    client.headers["Authorization"] = f"Bearer {body['data']['access_token']}"


def phone() -> str:
    global _seq
    _seq += 1
    return f"8{_seq % 10**9:09d}"


def employee_body(**overrides) -> dict:
    body = {
        "name": "Smoke Staff", "phone": phone(), "email": "staff@example.com", "address": "1 Gym Road",
        "role": "TRAINER", "aadhar_number": "1234 5678 9012", "pan_number": "abcde1234f",
        "emergency_contact_name": "Kin", "emergency_contact_phone": "9000000001",
        "emergency_contact_relation": "Brother", "date_of_joining": "2025-01-01", "education": "",
        "experience": "2 years", "morning_start": "06:00", "morning_end": "10:00",
        "evening_start": "17:00", "evening_end": "21:00",
    }
    body.update(overrides)
    return body


def payroll_body(**overrides) -> dict:
    body = {"base_salary": 28000, "bank_name": "SBI", "bank_account_number": "001122334455",
            "ifsc_code": "sbin0001234"}
    body.update(overrides)
    return body


def code_num(code: str) -> int:
    return int(code.rsplit("-", 1)[1])


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=30)
    login(owner, "owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    north = next(b for b in me["branches"] if b["branch_name"] == "North Branch")
    owner.headers["X-Branch-ID"] = north["id"]
    trainer = httpx.Client(base_url=BASE, timeout=30)
    login(trainer, "trainer@gym.com", "trainer123")
    today = date.today().isoformat()

    # ── employees: create + code sequence + PII ──────────────────────────
    e1 = check("create employee 1 (trainer role)", owner.post("/api/v1/employees", json=employee_body(
        name="Smoke Trainer"),), 201)["data"]
    e2 = check("create employee 2 (cleaner, no identity / emergency)", owner.post("/api/v1/employees", json={
        k: v for k, v in employee_body(name="Smoke Cleaner", role="CLEANER").items()
        if k not in ("aadhar_number", "pan_number", "emergency_contact_name", "emergency_contact_phone",
                     "emergency_contact_relation")}), 201)["data"]
    e3 = check("create employee 3 by trainer (no pii:view)", trainer.post("/api/v1/employees", json=employee_body(
        name="Smoke Helper", role="SERVICE_STAFF")), 201)["data"]
    expect("code format SG-EMP-###", bool(re.fullmatch(r"SG-EMP-\d{3,}", e1["employee_code"])), e1["employee_code"])
    expect("code sequence +1", code_num(e2["employee_code"]) == code_num(e1["employee_code"]) + 1,
           (e1["employee_code"], e2["employee_code"]))
    expect("code sequence +2 (trainer)", code_num(e3["employee_code"]) == code_num(e1["employee_code"]) + 2,
           e3["employee_code"])
    expect("new employee has no payroll yet", e1["base_salary"] == 0.0 and e1["bank_name"] is None
           and e1["bank_account_number"] is None, e1)
    expect("shift times returned", e1["morning_start"] == "06:00:00" and e1["evening_end"] == "21:00:00", e1)
    expect("identity and emergency are optional", e2["aadhar_number"] is None and e2["pan_number"] is None
           and e2["emergency_contact_name"] is None, e2)
    expect("id proof no longer in the API", "id_proof_type" not in e1 and "id_proof_number" not in e1, e1)

    # ── payroll & bank (separate form) ───────────────────────────────────
    e1 = check("set payroll 1", owner.put(f"/api/v1/employees/{e1['id']}/payroll", json=payroll_body()))["data"]
    e2 = check("set payroll 2 (cash, no bank)", owner.put(f"/api/v1/employees/{e2['id']}/payroll", json={
        "base_salary": 10000}))["data"]
    e3 = check("set payroll 3", owner.put(f"/api/v1/employees/{e3['id']}/payroll",
                                          json=payroll_body(base_salary=12000)))["data"]
    expect("owner sees plain PII", e1["aadhar_number"] == "123456789012" and e1["pan_number"] == "ABCDE1234F"
           and e1["bank_account_number"] == "001122334455", e1)
    expect("IFSC uppercased", e1["ifsc_code"] == "SBIN0001234", e1["ifsc_code"])
    expect("payroll without bank", e2["base_salary"] == 10000.0 and e2["bank_name"] is None, e2)
    t_view = check("trainer get employee", trainer.get(f"/api/v1/employees/{e3['id']}"))["data"]
    expect("trainer sees masked PII", t_view["aadhar_number"] == "XXXX-XXXX-9012"
           and t_view["pan_number"] == "XXXX-XXXX-234F" and t_view["bank_account_number"] == "XXXX-XXXX-4455", t_view)
    kept = check("payroll without account number keeps it", owner.put(f"/api/v1/employees/{e1['id']}/payroll", json={
        "base_salary": 28000, "bank_name": "SBI", "ifsc_code": "SBIN0001234"}))["data"]
    expect("stored account kept", kept["bank_account_number"] == "001122334455", kept)
    check("bank details go together", owner.put(f"/api/v1/employees/{e2['id']}/payroll", json={
        "base_salary": 10000, "bank_name": "SBI"}), 422)
    check("bad IFSC", owner.put(f"/api/v1/employees/{e1['id']}/payroll", json=payroll_body(ifsc_code="SBIN1001234")), 422)
    upi = check("payroll with UPI", owner.put(f"/api/v1/employees/{e1['id']}/payroll",
                                              json=payroll_body(upi_id=" Ravi.Kumar@OKAXIS ")))["data"]
    expect("UPI stored lower-cased", upi["upi_id"] == "ravi.kumar@okaxis", upi)
    bad_upi = owner.put(f"/api/v1/employees/{e1['id']}/payroll", json=payroll_body(upi_id="ravi.kumar"))
    expect("bad UPI → readable 422", bad_upi.status_code == 422 and bad_upi.json()["message"] == "Enter a valid UPI ID",
           bad_upi.text)
    check("email over 150 chars", owner.post("/api/v1/employees", json=employee_body(
        email=("a" * 145) + "@x.com")), 422)
    check("negative salary", owner.put(f"/api/v1/employees/{e1['id']}/payroll", json=payroll_body(base_salary=-1)), 422)
    o_view = check("owner get employee", owner.get(f"/api/v1/employees/{e3['id']}"))["data"]
    expect("owner sees plain PII of trainer-created row", o_view["pan_number"] == "ABCDE1234F", o_view)
    expect("default status ACTIVE", e1["status"] == "ACTIVE" and e1["base_salary"] == 28000.0, e1)

    # ── validation ───────────────────────────────────────────────────────
    check("bad PAN", owner.post("/api/v1/employees", json=employee_body(pan_number="ABCD1234F")), 422)
    check("bad Aadhaar", owner.post("/api/v1/employees", json=employee_body(aadhar_number="12345678901")), 422)
    check("bad phone", owner.post("/api/v1/employees", json=employee_body(phone="12345")), 422)
    check("blank address", owner.post("/api/v1/employees", json=employee_body(address="  ")), 422)
    check("duplicate phone", owner.post("/api/v1/employees", json=employee_body(phone=e1["phone"])), 409)
    check("no shift at all", owner.post("/api/v1/employees", json=employee_body(
        morning_start=None, morning_end=None, evening_start=None, evening_end=None)), 422)
    check("evening shift required", owner.post("/api/v1/employees", json=employee_body(
        evening_start=None, evening_end=None)), 422)
    check("shift needs both times", owner.post("/api/v1/employees", json=employee_body(evening_end=None)), 422)
    check("bad emergency phone still rejected", owner.post("/api/v1/employees", json=employee_body(
        emergency_contact_phone="123")), 422)
    check("shift ends after it starts", owner.post("/api/v1/employees", json=employee_body(
        morning_start="10:00", morning_end="06:00")), 422)
    check("morning ends before evening", owner.post("/api/v1/employees", json=employee_body(
        morning_end="18:00")), 422)

    # ── update ───────────────────────────────────────────────────────────
    upd = check("update employee (partial)", owner.put(f"/api/v1/employees/{e2['id']}", json={
        "name": "Smoke Cleaner II", "experience": "5 years", "pan_number": "zzzzz9999z"}))["data"]
    expect("update applied, others kept", upd["name"] == "Smoke Cleaner II" and upd["experience"] == "5 years"
           and upd["pan_number"] == "ZZZZZ9999Z" and upd["phone"] == e2["phone"] and upd["base_salary"] == 10000, upd)
    shifted = check("update evening shift", owner.put(f"/api/v1/employees/{e2['id']}", json={
        "evening_start": "16:30", "evening_end": "20:30"}))["data"]
    expect("evening shift saved", shifted["evening_start"] == "16:30:00" and shifted["morning_start"] == "06:00:00",
           shifted)
    check("update clearing a shift rejected", owner.put(f"/api/v1/employees/{e2['id']}", json={
        "evening_start": None, "evening_end": None}), 422)
    cleared = check("update clears optional PAN", owner.put(f"/api/v1/employees/{e2['id']}", json={
        "pan_number": None}))["data"]
    expect("PAN cleared", cleared["pan_number"] is None, cleared)
    check("update duplicate phone", owner.put(f"/api/v1/employees/{e2['id']}", json={"phone": e1["phone"]}), 409)
    check("update status TERMINATED rejected", owner.put(f"/api/v1/employees/{e2['id']}",
                                                         json={"status": "TERMINATED"}), 400)

    # ── list / trainers ──────────────────────────────────────────────────
    listed = check("list active search", owner.get("/api/v1/employees", params={"search": e1["employee_code"]}))
    expect("search by code finds employee", any(r["id"] == e1["id"] for r in listed["data"]), listed.get("total"))
    by_role = check("list role=CLEANER", owner.get("/api/v1/employees", params={"role": "CLEANER", "page_size": 500}))
    expect("role filter", all(r["role"] == "CLEANER" for r in by_role["data"])
           and any(r["id"] == e2["id"] for r in by_role["data"]))
    trainers = check("trainers dropdown", owner.get("/api/v1/employees/trainers"))["data"]
    expect("trainer listed", any(t["id"] == e1["id"] for t in trainers)
           and not any(t["id"] == e2["id"] for t in trainers))

    # ── feedback + profile ───────────────────────────────────────────────
    fb = check("feedback 4", owner.post(f"/api/v1/employees/{e1['id']}/feedback", json={
        "client_name": "Client A", "rating": 4, "comment": "Good", "feedback_date": "2025-03-01"}), 201)["data"]
    expect("avg after one = 4", fb["average_rating"] == 4.0, fb)
    fb = check("feedback 5 (trainer)", trainer.post(f"/api/v1/employees/{e1['id']}/feedback", json={
        "client_name": "Client B", "rating": 5}), 201)["data"]
    expect("avg = 4.5", fb["average_rating"] == 4.5, fb)
    expect("feedback_date defaults today", fb["feedback"]["feedback_date"] == today, fb)
    check("rating 6 rejected", owner.post(f"/api/v1/employees/{e1['id']}/feedback",
                                          json={"client_name": "X", "rating": 6}), 422)
    prof = check("profile (trainer)", owner.get(f"/api/v1/employees/{e1['id']}/profile"))["data"]
    training = prof.get("training") or {}
    expect("trainer profile has training", [f["rating"] for f in training.get("feedbacks", [])] == [5, 4]
           and training.get("average_rating") == 4.5 and isinstance(training.get("pt_clients"), list)
           and prof["employee"]["average_rating"] == 4.5, prof)
    expect("profile attendance month", prof["attendance"]["month_year"] == date.today().strftime("%m-%Y")
           and prof["attendance"]["days_elapsed"] == date.today().day, prof["attendance"])
    expect("owner sees payroll in profile", (prof.get("payroll") or {}).get("base_salary") == 28000.0, prof.get("payroll"))
    cprof = check("profile (cleaner)", owner.get(f"/api/v1/employees/{e2['id']}/profile"))["data"]
    expect("cleaner profile has no training section", cprof["training"] is None, cprof)
    tprof = check("profile as trainer (no salary:list)", trainer.get(f"/api/v1/employees/{e1['id']}/profile"))["data"]
    expect("payroll hidden without salary:list", tprof["payroll"] is None, tprof.get("payroll"))
    past = check("profile past month", owner.get(f"/api/v1/employees/{e1['id']}/profile",
                                                 params={"month": 1, "year": 2025}))["data"]["attendance"]
    expect("past month fully elapsed", past["month_year"] == "01-2025" and past["days_elapsed"] == 31, past)
    check("profile bad month", owner.get(f"/api/v1/employees/{e1['id']}/profile", params={"month": 13}), 422)

    # ── attendance ───────────────────────────────────────────────────────
    a1 = check("mark PRESENT today", owner.post("/api/v1/attendance/mark", json={
        "employee_id": e1["id"], "status": "PRESENT", "notes": "on time"}))["data"]
    expect("check-in set", a1["check_in_time"] is not None and a1["attendance_date"] == today, a1)
    a1b = check("re-mark LATE same day", owner.post("/api/v1/attendance/mark", json={
        "employee_id": e1["id"], "status": "LATE"}))["data"]
    expect("same record, check-in kept", a1b["id"] == a1["id"] and a1b["status"] == "LATE"
           and a1b["check_in_time"] == a1["check_in_time"], a1b)
    check("mark future date", owner.post("/api/v1/attendance/mark", json={
        "employee_id": e1["id"], "status": "PRESENT", "date": "2999-01-01"}), 400)
    check("checkout without check-in", owner.post(f"/api/v1/attendance/{e2['id']}/checkout"), 400)
    co = check("checkout", trainer.post(f"/api/v1/attendance/{e1['id']}/checkout"))["data"]
    expect("check-out set", co["check_out_time"] is not None, co)
    check("checkout twice", owner.post(f"/api/v1/attendance/{e1['id']}/checkout"), 400)
    pa = check("profile after marking", owner.get(f"/api/v1/employees/{e1['id']}/profile"))["data"]["attendance"]
    today_row = next((d for d in pa["days"] if d["date"] == today), None)
    expect("profile shows today's LATE with in/out", pa["late"] >= 1 and today_row is not None
           and today_row["status"] == "LATE" and today_row["check_in"] and today_row["check_out"], pa)
    daily = check("daily", owner.get("/api/v1/attendance/daily"))["data"]
    expect("daily has record with employee name", any(r["employee_id"] == e1["id"] and r["employee_name"] ==
                                                      "Smoke Trainer" for r in daily["records"]), daily["records"])
    expect("not_marked has unmarked active employee", any(n["id"] == e2["id"] for n in daily["not_marked"])
           and not any(n["id"] == e1["id"] for n in daily["not_marked"]))

    feb = {"PRESENT": ["01", "02", "03"], "LATE": ["04"], "ABSENT": ["05", "06"], "HALF_DAY": ["07"],
           "ON_LEAVE": ["08"]}
    for status, days in feb.items():
        for d in days:
            check(f"mark e1 {status} 2025-02-{d}", owner.post("/api/v1/attendance/mark", json={
                "employee_id": e1["id"], "status": status, "date": f"2025-02-{d}"}))
    past = check("mark e2 ABSENT 2025-02-10", owner.post("/api/v1/attendance/mark", json={
        "employee_id": e2["id"], "status": "ABSENT", "date": "2025-02-10"}))["data"]
    expect("past-date mark has no check-in", past["check_in_time"] is None, past)
    mon = check("monthly e1 02-2025", owner.get("/api/v1/attendance/monthly", params={
        "employee_id": e1["id"], "month": 2, "year": 2025}))["data"]
    expect("monthly summary", mon["summary"] == {"present": 3, "absent": 2, "late": 1, "half_day": 1,
                                                  "on_leave": 1, "total_days_in_month": 28}, mon["summary"])
    expect("monthly records", len(mon["records"]) == 8, len(mon["records"]))

    # ── salary ───────────────────────────────────────────────────────────
    one = check("calculate single e1 02-2025", owner.post("/api/v1/salary/calculate", json={
        "month": 2, "year": 2025, "employee_id": e1["id"]}))["data"]
    s1 = one["results"][0]["salary"]
    expect("e1 numbers (28000/28 → 2 absent)", s1["deductions"] == 2000.0 and s1["till_now_salary"] == 3000.0
           and s1["net_salary"] == 26000.0 and s1["days_present"] == 3 and s1["days_absent"] == 2
           and s1["days_late"] == 1 and s1["status"] == "PENDING" and s1["month_year"] == "02-2025", s1)
    expect("e1 absent dates", s1["absent_dates"] == ["2025-02-05", "2025-02-06"], s1["absent_dates"])
    bulk = check("calculate bulk 02-2025", owner.post("/api/v1/salary/calculate", json={"month": 2, "year": 2025}))
    res = {r["employee_id"]: r for r in bulk["data"]["results"]}
    expect("bulk covers e1, e2, e3", {e1["id"], e2["id"], e3["id"]} <= set(res), bulk["data"]["calculated"])
    s2 = res[e2["id"]]["salary"]
    expect("e2 rounding (10000/28 × 1)", s2["deductions"] == 357.14 and s2["net_salary"] == 9642.86
           and s2["till_now_salary"] == 0.0, s2)
    expect("e1 recalculated same row", res[e1["id"]]["salary"]["id"] == s1["id"]
           and res[e1["id"]]["outcome"] == "CALCULATED")
    month = check("salary month list", owner.get("/api/v1/salary", params={"month": 2, "year": 2025}))["data"]
    items = {i["employee_id"]: i for i in month["items"]}
    expect("month list has joined name + absent dates", items[e1["id"]]["employee_name"] == "Smoke Trainer"
           and items[e2["id"]]["absent_dates"] == ["2025-02-10"], items.get(e1["id"]))
    expect("total_payout = sum(net)", abs(month["total_payout"] - sum(i["net_salary"] for i in month["items"])) < 0.01,
           month["total_payout"])
    check("trainer cannot view payroll", trainer.get("/api/v1/salary"), 403)
    paid = check("pay e1", owner.put(f"/api/v1/salary/{s1['id']}/pay", json={"payment_method": "UPI"}))["data"]
    expect("paid", paid["status"] == "PAID" and paid["paid_date"] == today and paid["payment_method"] == "UPI", paid)
    check("pay twice", owner.put(f"/api/v1/salary/{s1['id']}/pay", json={"payment_method": "CASH"}), 409)
    check("pay bad method", owner.put(f"/api/v1/salary/{s2['id']}/pay", json={"payment_method": "CHEQUE"}), 422)
    re_bulk = check("re-calculate bulk", owner.post("/api/v1/salary/calculate", json={"month": 2, "year": 2025}))
    res = {r["employee_id"]: r for r in re_bulk["data"]["results"]}
    expect("PAID row skipped", res[e1["id"]]["outcome"] == "SKIPPED_PAID"
           and res[e1["id"]]["salary"]["status"] == "PAID" and re_bulk["data"]["skipped_paid"] >= 1, res[e1["id"]])
    expect("pending row recalculated", res[e2["id"]]["outcome"] == "CALCULATED")
    hist = check("salary history e1", owner.get(f"/api/v1/salary/employee/{e1['id']}"))["data"]
    expect("history has Feb 2025", any(h["month_year"] == "02-2025" for h in hist), hist)

    # ── terminate + archive ──────────────────────────────────────────────
    term = check("terminate e2", owner.patch(f"/api/v1/employees/{e2['id']}/terminate"))["data"]
    expect("terminated today", term["status"] == "TERMINATED" and term["date_of_termination"] == today, term)
    check("terminate twice", owner.patch(f"/api/v1/employees/{e2['id']}/terminate"), 400)
    check("update terminated", owner.put(f"/api/v1/employees/{e2['id']}", json={"name": "X"}), 400)
    check("payroll on terminated", owner.put(f"/api/v1/employees/{e2['id']}/payroll", json=payroll_body()), 400)
    check("feedback on terminated", owner.post(f"/api/v1/employees/{e2['id']}/feedback", json={
        "client_name": "Client X", "rating": 4, "comment": "late feedback"}), 400)
    check("mark attendance on terminated", owner.post("/api/v1/attendance/mark", json={
        "employee_id": e2["id"], "status": "PRESENT"}), 400)
    arch = check("archive list", owner.get("/api/v1/employees", params={"status": "archive", "search": e2["phone"]}))
    expect("terminated in archive", any(r["id"] == e2["id"] for r in arch["data"]))
    act = check("active list", owner.get("/api/v1/employees", params={"search": e2["phone"]}))
    expect("terminated not in active", not any(r["id"] == e2["id"] for r in act["data"]))
    allr = check("all list", owner.get("/api/v1/employees", params={"status": "all", "search": e2["phone"]}))
    expect("terminated in all", any(r["id"] == e2["id"] for r in allr["data"]))
    daily = check("daily after terminate", owner.get("/api/v1/attendance/daily"))["data"]
    expect("terminated not in not_marked", not any(n["id"] == e2["id"] for n in daily["not_marked"]))
    e4 = check("code after terminate keeps counting", owner.post("/api/v1/employees", json=employee_body(
        name="Smoke Next", role="ADMIN")), 201)["data"]
    expect("terminated codes count toward sequence", code_num(e4["employee_code"]) > code_num(e3["employee_code"]),
           e4["employee_code"])

    # cleanup — keep later runs' bulk payroll small
    for emp in (e1, e3, e4):
        check(f"cleanup terminate {emp['employee_code']}", owner.patch(f"/api/v1/employees/{emp['id']}/terminate"))

    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
