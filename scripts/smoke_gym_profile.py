"""Smoke test: gym profile (Gym Settings) — profile fields, GSTIN check, logo / terms upload + public links, branch
contacts (not unique) and head office, invoice letterhead, permissions.

    python -m scripts.smoke_gym_profile [base_url]

Puts the profile, logo, terms and branch contacts back as they were at the end.
"""
from __future__ import annotations

import base64
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
failures = 0
PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f80f000001010000ef7a2ea30000000049454e44ae426082")).decode()
PDF = base64.b64encode(b"%PDF-1.4\n% smoke terms\n").decode()


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


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    tok = check("login", c.post("/api/v1/auth/login", json={"email": "owner@gym.com", "password": "owner123"}))
    c.headers["Authorization"] = f"Bearer {tok['data']['access_token']}"
    me = check("me", c.get("/api/v1/auth/me"))["data"]
    c.headers["X-Branch-ID"] = {b["branch_name"]: b["id"] for b in me["branches"]}["Main Branch"]
    public = httpx.Client(base_url=BASE, timeout=30)

    print("\n── profile ──")
    before = check("get profile", c.get("/api/v1/gym-profile"))["data"]
    expect("Stag letterhead moved into the profile", before["gstin"] == "33CLMPA7280H2Z2" and before["code"] == "STAG",
           before)
    check("bad GSTIN → 422", c.put("/api/v1/gym-profile", json={"gstin": "12345"}), 422)
    saved = check("save profile", c.put("/api/v1/gym-profile", json={
        "tagline": "Smoke tagline", "invoice_footer": "Smoke footer", "gstin": "33abcde1234f1z5"}))["data"]
    expect("saved + GSTIN upper-cased", saved["tagline"] == "Smoke tagline" and saved["gstin"] == "33ABCDE1234F1Z5", saved)

    print("\n── files ──")
    check("logo as PDF → 400", c.put("/api/v1/gym-profile/logo", json={
        "file_name": "x.pdf", "content_type": "application/pdf", "data_base64": PDF}), 400)
    p = check("upload logo", c.put("/api/v1/gym-profile/logo", json={
        "file_name": "logo.png", "content_type": "image/png", "data_base64": PNG}))["data"]
    t = check("upload terms", c.put("/api/v1/gym-profile/terms", json={
        "file_name": "Terms.pdf", "content_type": "application/pdf", "data_base64": PDF}))["data"]
    expect("links returned", p["logo_url"] and t["terms_url"] and t["terms_file_name"] == "Terms.pdf", t)
    logo = public.get(t["logo_url"])
    terms = public.get(t["terms_url"])
    expect("logo public (no login)", logo.status_code == 200 and logo.headers["content-type"] == "image/png",
           logo.status_code)
    expect("terms public (no login)", terms.status_code == 200 and terms.content.startswith(b"%PDF"), terms.status_code)
    me2 = check("me", c.get("/api/v1/auth/me"))["data"]
    expect("logo on /auth/me", me2["user"]["organization_logo_url"] == t["logo_url"], me2["user"])
    check("unknown gym file → 404", public.get("/api/v1/public/gyms/NOPE/logo"), 404)

    print("\n── branches ──")
    branches = check("branches", c.get("/api/v1/branches"))["data"]
    main = next(b for b in branches if b["branch_name"] == "Main Branch")
    north = next(b for b in branches if b["branch_name"] == "North Branch")
    expect("counts + one head office", main["members_count"] > 0
           and sum(1 for b in branches if b["is_head_office"]) == 1, [(b["branch_name"], b["is_head_office"]) for b in branches])
    head = next(b for b in branches if b["is_head_office"])
    check("same phone on two branches is fine", c.put(f"/api/v1/branches/{north['id']}", json={
        "phone": "7598164812", "email": "north@example.com"}))
    check("same phone again", c.put(f"/api/v1/branches/{main['id']}", json={"phone": "7598164812"}))
    other = north if head["id"] != north["id"] else main
    moved = check("make another branch head office", c.put(f"/api/v1/branches/{other['id']}",
                                                           json={"is_head_office": True}))["data"]
    after = check("branches again", c.get("/api/v1/branches"))["data"]
    expect("only the new one is head office", moved["is_head_office"]
           and [b["id"] for b in after if b["is_head_office"]] == [other["id"]], after)
    check("delete head office → 400", c.delete(f"/api/v1/branches/{other['id']}"), 400)
    check("head office back", c.put(f"/api/v1/branches/{head['id']}", json={"is_head_office": True}))

    print("\n── invoice letterhead ──")
    pays = check("payments", c.get("/api/v1/payments", params={"page_size": 1}))["data"]
    if pays:
        inv = check("invoice", c.get(f"/api/v1/payments/{pays[0]['id']}/invoice"))["data"]
        expect("letterhead from profile", inv["tagline"] == "Smoke tagline" and inv["gstin"] == "33ABCDE1234F1Z5"
               and inv["invoice_footer"] == "Smoke footer" and inv["logo_url"] and inv["terms_url"], inv)

    print("\n── permissions ──")
    staff = httpx.Client(base_url=BASE, timeout=30)
    st = check("staff login", staff.post("/api/v1/auth/login", json={"email": "trainer@gym.com", "password": "trainer123"}))
    staff.headers["Authorization"] = f"Bearer {st['data']['access_token']}"
    check("staff reads profile", staff.get("/api/v1/gym-profile"))
    check("staff can't change it", staff.put("/api/v1/gym-profile", json={"tagline": "x"}), 403)

    print("\n── cleanup ──")
    check("profile back", c.put("/api/v1/gym-profile", json={k: before[k] for k in (
        "tagline", "invoice_footer", "gstin")}))
    check("remove logo", c.delete("/api/v1/gym-profile/logo"))
    check("remove terms", c.delete("/api/v1/gym-profile/terms"))
    check("north contacts back", c.put(f"/api/v1/branches/{north['id']}", json={"phone": north["phone"], "email": north["email"]}))
    check("main contacts back", c.put(f"/api/v1/branches/{main['id']}", json={"phone": main["phone"]}))

    print(f"\nFAILURES: {failures}" if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
