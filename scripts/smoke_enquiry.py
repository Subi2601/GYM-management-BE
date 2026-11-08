"""Smoke test: public enquiry form — branch link, submit → lead, duplicate phone, honeypot, bad token, regenerate.

    python -m scripts.smoke_enquiry [base_url]

Runs on North Branch with fresh phone numbers, deletes the leads it made at the end, and regenerates North's
link once (re-share the current link from the Leads screen after running it).
"""
from __future__ import annotations

import sys
import time

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
    _used.append(f"7{_seq % 10**9:09d}")
    return _used[-1]


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=30)
    tok = check("login", owner.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    owner.headers["Authorization"] = f"Bearer {tok['data']['access_token']}"
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    owner.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["North Branch"]
    # Every submit below comes from a different "address" so the per-IP limit doesn't trip the test.
    public = httpx.Client(base_url=BASE, timeout=30)

    def submit(token: str, body: dict, status: int = 201, ip: str | None = None) -> dict:
        return check(f"submit {body.get('name')}", public.post(f"/api/v1/public/enquiry/{token}", json=body,
                                                              headers={"X-Forwarded-For": ip or f"10.9.{_seq % 250}.{time.time_ns() % 250}"}),
                     status)

    print("\n── link ──")
    link = check("branch link", owner.get("/api/v1/leads/enquiry-form"))["data"]
    again = check("same link next time", owner.get("/api/v1/leads/enquiry-form"))["data"]
    expect("stable token", link["token"] == again["token"] and len(link["token"]) >= 24, link)
    info = check("public form info", public.get(f"/api/v1/public/enquiry/{link['token']}"))["data"]
    expect("shows gym + branch", info["branch_name"] == "North Branch" and info["organization_name"], info)
    check("unknown token → 404", public.get("/api/v1/public/enquiry/" + "x" * 32), 404)
    check("bad token format → 422", public.get("/api/v1/public/enquiry/short"), 422)

    print("\n── submit ──")
    p = phone()
    r = submit(link["token"], {"name": "Form Lead", "phone": p, "goal": "WEIGHT_LOSS", "preferred_time": "EVENING",
                               "join_when": "THIS_WEEK", "location": "Anna Nagar", "message": "Ladies batch?"})
    expect("thank-you message", "Form Lead" in (r.get("message") or ""), r)
    leads = check("find lead", owner.get("/api/v1/leads", params={"search": p}))
    lead = leads["data"][0] if leads["data"] else {}
    expect("one NEW lead, source form", leads["total"] == 1 and lead.get("status") == "NEW"
           and lead.get("source") == "ENQUIRY_FORM", lead)
    expect("follow-up today, details in notes", lead.get("next_follow_up_date") is not None
           and "evening" in (lead.get("notes") or "") and "Ladies batch?" in (lead.get("notes") or ""), lead)
    expect("goal + area + join date", lead.get("goal") == "WEIGHT_LOSS" and lead.get("location") == "Anna Nagar"
           and lead.get("plan_to_join_date") is not None, lead)

    submit(link["token"], {"name": "Form Lead", "phone": p, "message": "Calling back?"})
    leads = check("same phone again", owner.get("/api/v1/leads", params={"search": p}))
    expect("no duplicate, note added", leads["total"] == 1 and "Enquired again" in (leads["data"][0]["notes"] or ""),
           leads)

    submit(link["token"], {"name": "x", "phone": "123"}, 422)
    submit(link["token"], {"name": "", "phone": phone()}, 422)
    hp = phone()
    submit(link["token"], {"name": "Bot", "phone": hp, "website": "http://spam"})
    expect("honeypot stores nothing", check("bot lead?", owner.get("/api/v1/leads", params={"search": hp}))
           ["total"] == 0, "")

    print("\n── limits ──")
    lp = phone()
    for i in range(3):
        submit(link["token"], {"name": f"Repeat {i}", "phone": lp})
    submit(link["token"], {"name": "Repeat 4", "phone": lp}, 429)
    ip = f"10.250.{_seq % 250}.7"
    for i in range(10):
        submit(link["token"], {"name": f"Same IP {i}", "phone": phone()}, ip=ip)
    submit(link["token"], {"name": "Same IP 11", "phone": phone()}, 429, ip=ip)

    print("\n── regenerate ──")
    new = check("regenerate", owner.post("/api/v1/leads/enquiry-form/regenerate"))["data"]
    expect("new token", new["token"] != link["token"], "")
    check("old link → 404", public.get(f"/api/v1/public/enquiry/{link['token']}"), 404)
    check("new link works", public.get(f"/api/v1/public/enquiry/{new['token']}"))

    print("\n── cleanup ──")
    removed = 0
    for p in _used:
        for lead in owner.get("/api/v1/leads", params={"search": p}).json().get("data") or []:
            removed += owner.delete(f"/api/v1/leads/{lead['id']}").status_code == 200
    print(f"deleted {removed} test lead(s)")

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
