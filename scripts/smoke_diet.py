"""Diet plans + food catalogue smoke test against a running server.

    python -m scripts.smoke_diet [base_url]

Creates fresh members each run (re-runnable). Subscriptions are inserted directly through SQLAlchemy so this
test does not depend on the subscriptions API. Prints one line per check.
"""
from __future__ import annotations

import asyncio
import random
import sys
import time
from datetime import timedelta
from uuid import UUID

import httpx
from sqlalchemy import select

from app.core import timeutil
from app.database import AsyncSessionLocal, engine
from app.models.billing import Plan, Subscription
from app.models.member import Member

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8014"
TAG = f"Diet{int(time.time()) % 1_000_000}"
failures = 0


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
    print(f"{'PASS' if condition else 'FAIL'} {label} {'' if condition else detail}")


def login(client: httpx.Client, email: str, password: str) -> None:
    body = check(f"login {email}", client.post("/api/v1/auth/login", json={"email": email, "password": password}))
    client.headers["Authorization"] = f"Bearer {body['data']['access_token']}"


def new_member(client: httpx.Client, label: str, gender: str = "MALE") -> dict:
    phone = "9" + "".join(random.choice("0123456789") for _ in range(9))
    body = check(f"create member {label}", client.post("/api/v1/members", json={
        "name": f"{TAG} {label}", "phone": phone, "gender": gender}), 201)
    return body["data"]


async def _subscribe(member_id: str, plan_names: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        member = (await db.execute(select(Member).where(Member.id == UUID(member_id)))).scalar_one()
        start = timeutil.today()
        for name in plan_names:
            plan = (await db.execute(select(Plan).where(Plan.branch_id == member.branch_id, Plan.name == name,
                                                        Plan.is_delete.is_(False)))).scalars().first()
            assert plan is not None, f"seed plan missing: {name}"
            db.add(Subscription(organization_id=member.organization_id, branch_id=member.branch_id,
                                member_id=member.id, plan_id=plan.id, start_date=start,
                                end_date=start + timedelta(days=plan.duration_days)))
        await db.commit()


def subscribe(member_id: str, *plan_names: str) -> None:
    async def run() -> None:
        try:
            await _subscribe(member_id, list(plan_names))
        finally:
            await engine.dispose()
    asyncio.run(run())


def eligible(client: httpx.Client) -> dict[str, dict]:
    body = check("eligible members", client.get("/api/v1/diet-plans/eligible-members",
                                                params={"search": TAG, "page_size": 100}))
    return {row["name"]: row for row in body.get("data", [])}


def main() -> None:
    owner = httpx.Client(base_url=BASE, timeout=20)
    login(owner, "owner@gym.com", "owner123")
    me = check("me", owner.get("/api/v1/auth/me"))["data"]
    main_branch = next(b for b in me["branches"] if b["branch_name"] == "Main Branch")
    owner.headers["X-Branch-ID"] = main_branch["id"]

    # ── eligibility ──────────────────────────────────────────────────────
    none_m = new_member(owner, "NoPlan")
    basic_m = new_member(owner, "Quarterly")
    std_m = new_member(owner, "Standard")
    prem_m = new_member(owner, "Premium", gender="FEMALE")
    subscribe(basic_m["id"], "Quarterly Membership")
    subscribe(std_m["id"], "Monthly Membership", "Diet Plan - Standard")
    subscribe(prem_m["id"], "Diet Plan - Premium")

    rows = eligible(owner)
    expect("no subscription -> excluded", f"{TAG} NoPlan" not in rows, list(rows))
    expect("quarterly -> BASIC", rows.get(f"{TAG} Quarterly", {}).get("eligible_tier") == "BASIC", rows)
    expect("standard add-on -> STANDARD", rows.get(f"{TAG} Standard", {}).get("eligible_tier") == "STANDARD", rows)
    expect("premium add-on -> PREMIUM", rows.get(f"{TAG} Premium", {}).get("eligible_tier") == "PREMIUM", rows)
    expect("no plan yet", rows.get(f"{TAG} Standard", {}).get("has_plan") is False, rows)

    check("get plan before configure -> 404", owner.get(f"/api/v1/diet-plans/member/{std_m['id']}"), 404)
    calc = {"weight": 70, "height": 175, "age": 30, "activity_level": 1.55, "category": "VEG"}
    check("configure ineligible member -> 400",
          owner.put(f"/api/v1/diet-plans/member/{none_m['id']}", json={**calc, "tier": "BASIC"}), 400)
    check("tier above eligibility -> 400",
          owner.put(f"/api/v1/diet-plans/member/{basic_m['id']}", json={**calc, "tier": "STANDARD"}), 400)
    check("bad activity level -> 422",
          owner.put(f"/api/v1/diet-plans/member/{std_m['id']}", json={**calc, "tier": "STANDARD",
                                                                      "activity_level": 1.3}), 422)
    check("add item before configure -> 400",
          owner.post(f"/api/v1/diet-plans/member/{std_m['id']}/items",
                     json={"food_item_id": str(UUID(int=1)), "meal_time": "Lunch"}), 400)

    # ── foods ────────────────────────────────────────────────────────────
    foods = check("list foods", owner.get("/api/v1/food-items", params={"page_size": 500}))
    by_name = {f["name"]: f for f in foods["data"]}
    expect("14 platform foods visible", sum(f["is_platform"] for f in foods["data"]) >= 14, len(foods["data"]))
    chicken, oats = by_name["Chicken Breast (Grilled)"], by_name["Oats (Cooked)"]
    nv = check("filter category NON_VEG", owner.get("/api/v1/food-items", params={"category": "NON_VEG"}))
    expect("category filter", all(f["category"] == "NON_VEG" for f in nv["data"]) and nv["total"] >= 3)
    srch = check("search foods", owner.get("/api/v1/food-items", params={"search": "almond"}))
    expect("search filter", [f["name"] for f in srch["data"]] == ["Almonds"], srch["data"])
    check("negative calories -> 422", owner.post("/api/v1/food-items", json={
        "name": f"{TAG} Bad", "category": "VEG", "calories": -1}), 422)
    sprouts = check("create org food", owner.post("/api/v1/food-items", json={
        "name": f"{TAG} Sprouts", "category": "VEGAN", "calories": 100, "protein": 8, "carbs": 15, "fats": 1,
        "fiber": 4, "serving_unit": "grams", "nutritional_benefits": "Fibre"}), 201)["data"]
    expect("org food not platform", sprouts["is_platform"] is False and sprouts["organization_id"] is not None)
    check("duplicate food name -> 409", owner.post("/api/v1/food-items", json={
        "name": f"{TAG} Sprouts", "category": "VEG", "calories": 1}), 409)
    temp = check("create temp food", owner.post("/api/v1/food-items", json={
        "name": f"{TAG} Temp", "category": "VEG", "calories": 10}), 201)["data"]
    check("delete platform food -> 403", owner.delete(f"/api/v1/food-items/{chicken['id']}"), 403)

    # ── BASIC plan ───────────────────────────────────────────────────────
    basic_plan = check("configure BASIC plan", owner.put(f"/api/v1/diet-plans/member/{basic_m['id']}",
                                                         json={**calc, "tier": "BASIC"}))["data"]
    expect("basic: unlimited, not editable",
           basic_plan["monthly_update_limit"] is None and basic_plan["items_editable"] is False, basic_plan)
    check("BASIC add item -> 400", owner.post(f"/api/v1/diet-plans/member/{basic_m['id']}/items",
                                              json={"food_item_id": chicken["id"], "meal_time": "Lunch"}), 400)

    # ── STANDARD plan: maths ─────────────────────────────────────────────
    plan = check("configure STANDARD plan (mod 1)",
                 owner.put(f"/api/v1/diet-plans/member/{std_m['id']}", json={**calc, "tier": "STANDARD"}))["data"]
    # 70kg / 1.75m² = 22.857; BMR = 700 + 1093.75 - 150 + 5 = 1648.75; TDEE = ×1.55 = 2555.5625
    # protein 40% /4 = 255.6, carbs 30% /4 = 191.7, fats 30% /9 = 85.2
    want = {"bmi": 22.9, "bmi_status": "Normal", "bmr": 1649, "tdee": 2556, "target_calories": 2556,
            "target_protein": 256, "target_carbs": 192, "target_fats": 85, "modification_count": 1,
            "monthly_update_limit": 2, "weight": 70, "height": 175, "age": 30, "activity_level": 1.55}
    got = {k: plan.get(k) for k in want}
    expect("STANDARD maths", got == want, got)
    expect("four meals in order", [m["meal_time"] for m in plan["meals"]] ==
           ["Breakfast", "Lunch", "Evening Snack", "Dinner"], plan["meals"])

    fem = check("configure PREMIUM female plan", owner.put(f"/api/v1/diet-plans/member/{prem_m['id']}", json={
        "tier": "PREMIUM", "weight": 60, "height": 160, "age": 25, "activity_level": 1.2}))["data"]
    # BMR = 600 + 1000 - 125 - 161 = 1314; TDEE 1576.8 → P 157.7→158, C 118.3→118, F 52.6→53
    got = {k: fem[k] for k in ("bmi", "bmr", "tdee", "target_protein", "target_carbs", "target_fats",
                               "monthly_update_limit")}
    expect("PREMIUM female maths", got == {"bmi": 23.4, "bmr": 1314, "tdee": 1577, "target_protein": 158,
                                           "target_carbs": 118, "target_fats": 53,
                                           "monthly_update_limit": None}, got)

    # ── STANDARD plan: items ─────────────────────────────────────────────
    url = f"/api/v1/diet-plans/member/{std_m['id']}/items"
    check("quantity 0 -> 422", owner.post(url, json={"food_item_id": chicken["id"], "meal_time": "Lunch",
                                                     "quantity": 0}), 422)
    check("add chicken 150g to Lunch", owner.post(url, json={"food_item_id": chicken["id"], "meal_time": "Lunch",
                                                            "quantity": 150}), 201)
    check("add oats (default 100g) to Breakfast", owner.post(url, json={"food_item_id": oats["id"],
                                                                         "meal_time": "Breakfast"}), 201)
    plan = check("add org sprouts 50g to Evening Snack",
                 owner.post(url, json={"food_item_id": sprouts["id"], "meal_time": "Evening Snack",
                                       "quantity": 50}), 201)["data"]
    meals = {m["meal_time"]: m for m in plan["meals"]}
    lunch = meals["Lunch"]["items"][0]
    expect("chicken item totals", (lunch["calories"], lunch["protein"], lunch["carbs"], lunch["fats"],
                                   lunch["serving_unit"]) == (247.5, 46.5, 0, 5.4, "grams"), lunch)
    expect("breakfast totals", meals["Breakfast"]["totals"] == {"calories": 68, "protein": 2.4, "carbs": 12,
                                                               "fats": 1.4}, meals["Breakfast"]["totals"])
    # 247.5 + 68 + 50 = 365.5 kcal; P 46.5 + 2.4 + 4 = 52.9; C 0 + 12 + 7.5 = 19.5; F 5.4 + 1.4 + 0.5 = 7.3
    expect("plan totals", plan["totals"] == {"calories": 365.5, "protein": 52.9, "carbs": 19.5, "fats": 7.3},
           plan["totals"])

    check("delete food used in plan -> 400", owner.delete(f"/api/v1/food-items/{sprouts['id']}"), 400)
    check("delete unused org food", owner.delete(f"/api/v1/food-items/{temp['id']}"))
    check("deleted food gone", owner.delete(f"/api/v1/food-items/{temp['id']}"), 404)

    oats_item = meals["Breakfast"]["items"][0]["id"]
    check("remove item via other member -> 404",
          owner.delete(f"/api/v1/diet-plans/member/{prem_m['id']}/items/{oats_item}"), 404)
    plan = check("remove oats", owner.delete(f"{url}/{oats_item}"))["data"]
    expect("oats really removed", not plan["meals"][0]["items"] and
           plan["totals"] == {"calories": 297.5, "protein": 50.5, "carbs": 7.5, "fats": 5.9}, plan["totals"])
    plan = check("GET plan after remove", owner.get(f"/api/v1/diet-plans/member/{std_m['id']}"))["data"]
    expect("removal persisted", plan["totals"]["calories"] == 297.5, plan["totals"])

    share = check("share text", owner.get(f"/api/v1/diet-plans/member/{std_m['id']}/share-text"))["data"]
    expect("share phone 91 prefix", share["phone"] == "91" + std_m["phone"], share["phone"])
    expected_text = (f"*STAG FITNESS - DIET PLAN*\n*Member:* {TAG} Standard\n*Tier:* STANDARD\n\n"
                     "*Daily Targets:*\n- Calories: 2556 kcal\n- Protein: 256g\n- Carbs: 192g\n- Fats: 85g\n\n"
                     "*Meal Schedule:*\n*Lunch:* Chicken Breast (Grilled) (247.5 kcal)\n"
                     f"*Evening Snack:* {TAG} Sprouts (50 kcal)\n")
    expect("share text matches old shareWhatsApp()", share["text"] == expected_text, repr(share["text"]))

    # ── STANDARD monthly limit ───────────────────────────────────────────
    plan = check("update STANDARD plan (mod 2)", owner.put(f"/api/v1/diet-plans/member/{std_m['id']}",
                                                          json={**calc, "weight": 72, "tier": "STANDARD"}))["data"]
    expect("modification_count 2", plan["modification_count"] == 2 and plan["weight"] == 72, plan)
    check("3rd modification in month -> 400", owner.put(f"/api/v1/diet-plans/member/{std_m['id']}",
                                                         json={**calc, "tier": "STANDARD"}), 400)
    rows = eligible(owner)
    row = rows.get(f"{TAG} Standard", {})
    expect("eligible row shows plan", row.get("has_plan") is True and row.get("plan_tier") == "STANDARD"
           and row.get("last_modified_date") == str(timeutil.today()), row)

    # ── trainer ──────────────────────────────────────────────────────────
    trainer = httpx.Client(base_url=BASE, timeout=20)
    login(trainer, "trainer@gym.com", "trainer123")
    check("trainer can list foods", trainer.get("/api/v1/food-items"))
    check("trainer cannot create food", trainer.post("/api/v1/food-items", json={
        "name": f"{TAG} T", "category": "VEG", "calories": 1}), 403)
    check("trainer eligible-members -> 403", trainer.get("/api/v1/diet-plans/eligible-members"), 403)
    check("trainer get plan -> 403", trainer.get(f"/api/v1/diet-plans/member/{std_m['id']}"), 403)
    check("trainer configure -> 403", trainer.put(f"/api/v1/diet-plans/member/{std_m['id']}",
                                                  json={**calc, "tier": "STANDARD"}), 403)
    check("trainer add item -> 403", trainer.post(url, json={"food_item_id": chicken["id"], "meal_time": "Lunch"}),
          403)

    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
