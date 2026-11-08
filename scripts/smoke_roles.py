"""Smoke test: roles & access — the gym's role hierarchy (Owner > Sub-admin > Manager > Staff), custom roles,
owner-only access, branch switching, staff logins with a role and the level rules.

    python -m scripts.smoke_roles [base_url]

Creates fresh employees / logins / a custom role every run (in Main Branch) and cleans the role up at the end.
"""
from __future__ import annotations

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
RUN = int(time.time()) % 10**7
failures = 0
_seq = int(time.time() * 10) % 10**8
PASSWORD = "Smoke@1234"


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
    return f"9{_seq % 10**9:09d}"


def client(email: str, password: str, branch: str | None = None) -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=30)
    body = check(f"login {email}", c.post("/api/v1/auth/login", json={"email": email, "password": password}))
    c.headers["Authorization"] = f"Bearer {body['data']['access_token']}"
    if branch:
        c.headers["X-Branch-ID"] = branch
    return c


def main() -> None:
    owner = client("owner@gym.com", "owner123")
    me = check("owner me", owner.get("/api/v1/auth/me"))["data"]
    main_branch = {b["branch_name"]: b["id"] for b in me["branches"]}["Main Branch"]
    owner.headers["X-Branch-ID"] = main_branch
    expect("owner role name", me["user"]["role_name"] == "Owner" and me["user"]["role_level"] == 100, me["user"])
    expect("owner can manage roles", {"role:list", "role:manage"} <= set(me["permissions"]), "")

    print("\n── built-in roles ──")
    roles = {r["code"]: r for r in check("list roles", owner.get("/api/v1/roles"))["data"]}
    expect("4 built-in roles", {"OWNER", "SUB_ADMIN", "MANAGER", "STAFF"} <= set(roles), list(roles))
    expect("levels", [roles[c]["level"] for c in ("OWNER", "SUB_ADMIN", "MANAGER", "STAFF")] == [100, 80, 50, 10],
           "")
    expect("owner not editable", roles["OWNER"]["editable"] is False and roles["MANAGER"]["editable"] is True, "")
    expect("sub-admin all branches", roles["SUB_ADMIN"]["all_branches"] and not roles["MANAGER"]["all_branches"], "")
    cat = check("catalog", owner.get("/api/v1/roles/catalog"))["data"]
    flags = {p["code"]: p for m in cat for s in m["screens"] for p in s["permissions"]}
    expect("owner-only flagged", flags["role:manage"]["owner_only"] and flags["branch:create"]["owner_only"], "")
    expect("switch flagged", flags["branch:switch"]["all_branches_only"], "")
    sub = check("sub-admin detail", owner.get(f"/api/v1/roles/{roles['SUB_ADMIN']['id']}"))["data"]
    expect("sub-admin: no roles & access", "role:manage" not in sub["permissions"]
           and "branch:switch" in sub["permissions"], "")
    staff = check("staff detail", owner.get(f"/api/v1/roles/{roles['STAFF']['id']}"))["data"]
    expect("staff: collects, no revenue", "payment:create" in staff["permissions"]
           and "payment:stats" not in staff["permissions"] and "payment:list" not in staff["permissions"], "")
    check("owner access can't change → 400",
          owner.put(f"/api/v1/roles/{roles['OWNER']['id']}/permissions", json={"codes": []}), 400)
    check("built-in role can't be deleted → 400", owner.delete(f"/api/v1/roles/{roles['STAFF']['id']}"), 400)

    print("\n── custom role ──")
    rec = check("create Receptionist (staff level)", owner.post("/api/v1/roles", json={
        "name": f"Receptionist {RUN}", "description": "Front desk", "level": 10}), 201)["data"]
    expect("copied staff ticks", set(rec["permissions"]) == set(staff["permissions"]), rec["permissions"])
    check("duplicate name → 409", owner.post("/api/v1/roles", json={"name": f"receptionist {RUN}", "level": 10}), 409)
    check("owner level → 400", owner.post("/api/v1/roles", json={"name": f"Boss {RUN}", "level": 100}), 400)
    check("owner-only tick → 400", owner.put(f"/api/v1/roles/{rec['id']}/permissions", json={
        "codes": ["member:list", "role:manage"]}), 400)
    check("branch switch on a branch role → 400", owner.put(f"/api/v1/roles/{rec['id']}/permissions", json={
        "codes": ["member:list", "branch:switch"]}), 400)
    check("unknown code → 400", owner.put(f"/api/v1/roles/{rec['id']}/permissions", json={"codes": ["x:y"]}), 400)
    rec = check("set ticks", owner.put(f"/api/v1/roles/{rec['id']}/permissions", json={
        "codes": ["member:list", "member:create", "lead:list", "lead:create"]}))["data"]
    expect("ticks saved (+ own account)", set(rec["permissions"]) == {
        "member:list", "member:create", "lead:list", "lead:create", "auth:me"}, rec["permissions"])

    print("\n── staff logins with roles ──")
    def employee(name: str, role: str = "TRAINER") -> dict:
        return check(f"employee {name}", owner.post("/api/v1/employees", json={
            "name": f"{name} {RUN}", "phone": phone(), "email": f"{name.lower()}.{RUN}@example.com",
            "address": "1 Gym Road", "role": role, "date_of_joining": "2025-01-01",
            "morning_start": "06:00", "morning_end": "10:00",
            "evening_start": "17:00", "evening_end": "21:00"}), 201)["data"]

    e_rec = employee("Desk")
    login = check("login with Receptionist", owner.put(f"/api/v1/employees/{e_rec['id']}/login", json={
        "password": PASSWORD, "role_id": rec["id"]}))["data"]
    expect("login shows role", login["role_name"] == rec["name"], login)
    desk = client(e_rec["email"], PASSWORD)
    dme = check("desk me", desk.get("/api/v1/auth/me"))["data"]
    expect("desk has only the ticks", set(dme["permissions"]) == set(rec["permissions"]), dme["permissions"])
    expect("desk fixed to branch", dme["can_switch_branch"] is False, dme)
    check("desk can't see roles → 403", desk.get("/api/v1/roles"), 403)
    check("desk can list members", desk.get("/api/v1/members"))
    check("desk can't see payments → 403", desk.get("/api/v1/payments"), 403)

    e_mgr = employee("Lead", "MANAGER")
    mlogin = check("manager login (default role)", owner.put(f"/api/v1/employees/{e_mgr['id']}/login", json={
        "password": PASSWORD}))["data"]
    expect("manager staff → Manager role", mlogin["role_name"] == "Manager", mlogin)
    mgr = client(e_mgr["email"], PASSWORD)
    mme = check("manager me", mgr.get("/api/v1/auth/me"))["data"]
    expect("manager: own branch, sees payments", not mme["can_switch_branch"] and "payment:stats" in mme["permissions"],
           "")
    can_give = {r["code"] for r in check("manager assignable", mgr.get("/api/v1/roles/assignable"))["data"]}
    expect("manager can give only lower roles", "STAFF" in can_give and not can_give & {"MANAGER", "SUB_ADMIN",
                                                                                          "OWNER"}, can_give)
    e_new = employee("Helper")
    check("manager gives Sub-admin → 403", mgr.put(f"/api/v1/employees/{e_new['id']}/login", json={
        "password": PASSWORD, "role_id": roles["SUB_ADMIN"]["id"]}), 403)
    check("manager gives Staff", mgr.put(f"/api/v1/employees/{e_new['id']}/login", json={
        "password": PASSWORD, "role_id": roles["STAFF"]["id"]}))
    check("manager can't change own-level login → 400", mgr.put(f"/api/v1/employees/{e_mgr['id']}/login", json={
        "password": "Other@1234"}), 400)

    e_sub = employee("Deputy", "ADMIN")
    check("owner gives Sub-admin", owner.put(f"/api/v1/employees/{e_sub['id']}/login", json={
        "password": PASSWORD, "role_id": roles["SUB_ADMIN"]["id"]}))
    deputy = client(e_sub["email"], PASSWORD)
    sme = check("sub-admin me", deputy.get("/api/v1/auth/me"))["data"]
    expect("sub-admin sees all branches", sme["can_switch_branch"] and len(sme["branches"]) >= 2, sme["branches"])
    check("sub-admin can't open roles → 403", deputy.get("/api/v1/roles"), 403)

    print("\n── cleanup ──")
    check("role in use can't be deleted → 400", owner.delete(f"/api/v1/roles/{rec['id']}"), 400)
    check("move desk to Staff", owner.put(f"/api/v1/employees/{e_rec['id']}/login", json={
        "role_id": roles["STAFF"]["id"]}))
    check("delete custom role", owner.delete(f"/api/v1/roles/{rec['id']}"))
    for e in (e_rec, e_mgr, e_new, e_sub):
        check(f"terminate {e['name']}", owner.patch(f"/api/v1/employees/{e['id']}/terminate"))

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
