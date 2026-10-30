"""End-to-end API smoke test against a running server.

    python -m scripts.smoke_test [base_url]

Walks the main flows as the seeded owner and trainer and prints one line per check.
"""
from __future__ import annotations

import sys
from datetime import date

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
failures = 0


def check(label: str, resp: httpx.Response, expect: int = 200) -> dict:
    global failures
    ok = resp.status_code == expect
    if not ok:
        failures += 1
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    print(f"{'PASS' if ok else 'FAIL'} {label}: {resp.status_code} {'' if ok else body}")
    return body


def login(client: httpx.Client, email: str, password: str) -> None:
    body = check(f"login {email}", client.post("/api/v1/auth/login", json={"email": email, "password": password}))
    client.headers["Authorization"] = f"Bearer {body['data']['access_token']}"


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=20)
    login(owner, "owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    owner.headers["X-Branch-ID"] = main_branch["id"]

    check("bad login", httpx.post(f"{BASE}/api/v1/auth/login",
                                  json={"email": "owner@gym.com", "password": "nope"}), 401)
    check("no token", httpx.get(f"{BASE}/api/v1/members"), 401)

    reg = check("next reg id", owner.get("/api/v1/members/next-registration-id"))["data"]["code"]
    phone = f"9{date.today():%m%d}{len(reg):02d}{reg[-3:]}"[:10].ljust(10, "0")
    member = check("create member", owner.post("/api/v1/members", json={
        "name": "Smoke Member", "phone": phone, "gender": "MALE", "weight": 72, "height": 175,
        "dob": "1995-04-12", "id_proof_type": "Aadhar", "id_proof_number": "123412341234", "email": ""}), 201)
    member_id = member["data"]["id"]
    check("duplicate phone", owner.post("/api/v1/members", json={"name": "Dup", "phone": phone}), 409)
    check("invalid phone", owner.post("/api/v1/members", json={"name": "Bad", "phone": "123"}), 422)
    listed = check("list members", owner.get("/api/v1/members", params={"search": "Smoke"}))
    print("     members found:", listed.get("total"))

    trainer = httpx.Client(base_url=BASE, timeout=20)
    login(trainer, "trainer@gym.com", "trainer123")
    check("trainer blocked from other branch",
          trainer.get("/api/v1/members", headers={"X-Branch-ID": main_branch["id"]}), 403)
    check("trainer cannot see member of other branch", trainer.get(f"/api/v1/members/{member_id}"), 404)

    extra = globals().get("extra_checks")
    if extra:
        extra(owner, trainer, member_id, main_branch)

    check("logout", owner.post("/api/v1/auth/logout"))
    check("token dead after logout", owner.get("/api/v1/auth/me"), 401)
    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
