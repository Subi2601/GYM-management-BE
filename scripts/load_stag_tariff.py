"""Load the STAG tariff (STAG TARIFF.pdf) as plans in every branch of the STAG organization.

    python -m scripts.load_stag_tariff [--hide-old]

Re-runnable: a plan is added only when its category has no plan of that name in the branch. --hide-old hides
(never deletes) the smoke-test plans so the desk sees the tariff; "Show" on Plans & Pricing brings them back.
The seed's demo plans (Monthly / Quarterly / Annual Membership …) stay as they are — the smoke tests use them.
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import or_, select

from app.core.enums import PlanServiceType, PlanType
from app.database import AsyncSessionLocal
from app.models.billing import Plan, PlanCategory
from app.models.organization import Branch, Organization

MONTHS = {1: "1 Month", 3: "3 Months", 6: "6 Months", 12: "12 Months"}

# category: [(months, price, extra)]  — extra: group_size, free_members, id_check, all_branches
MEMBERSHIPS: dict[str, tuple[list[tuple[int, int]], dict]] = {
    "General": ([(1, 1999), (3, 5099), (6, 8999), (12, 11999)], {}),
    "Student - School": ([(1, 1499), (3, 3999), (6, 6999), (12, 9999)], {"id_check": "School ID card"}),
    "Student - College": ([(1, 1799), (3, 4499), (6, 7999), (12, 10999)], {"id_check": "College ID card"}),
    "Couple": ([(3, 9499), (6, 15999), (12, 30999)], {"group_size": 2}),
    "Family": ([(3, 13999), (6, 23999), (12, 30999)], {"group_size": 3, "all_branches": True}),
    "Friends": ([(3, 20499), (6, 35999), (12, 47999)], {"group_size": 5, "free_members": 1, "all_branches": True}),
    "Corporate": ([(3, 22999), (6, 39999), (12, 52999)], {"group_size": 5, "all_branches": True}),
}
DESCRIPTIONS = {
    "Student - School": "Exclusive for school students. Valid school ID mandatory.",
    "Student - College": "Exclusive for college students. Valid college ID mandatory.",
    "Couple": "Couples or two friends joining together. Full access to the general workout area.",
    "Family": "Family of 3. Flexible timings, fitness assessment, diet & workout guidance. Valid at both branches.",
    "Friends": "Pay for 4, the 5th joins free. Free fitness consultation. Valid at all STAG branches.",
    "Corporate": "Office team of 5. Monthly progress tracking, one-time nutrition consultation. All branches.",
}
# name, sessions, validity days, price
PT = [("Fit Start Program", 24, 60, 12000), ("Strong 12 Program", 48, 100, 22000),
      ("Lean 16 Program", 64, 130, 28000), ("Elite 20 Program", 80, 150, 34000)]


async def main(hide_old: bool) -> None:
    async with AsyncSessionLocal() as db:
        org = (await db.execute(select(Organization).where(Organization.code == "STAG"))).scalar_one()
        cats = {c.name: c for c in (await db.execute(
            select(PlanCategory).where(PlanCategory.organization_id == org.id,
                                       PlanCategory.is_delete.is_(False)))).scalars()}
        branches = (await db.execute(select(Branch).where(Branch.organization_id == org.id,
                                                          Branch.is_delete.is_(False)))).scalars().all()
        added = hidden = 0
        for branch in branches:
            existing = {(p.category_id, p.name) for p in (await db.execute(
                select(Plan).where(Plan.branch_id == branch.id, Plan.is_delete.is_(False)))).scalars()}

            def want(category: str, name: str, **fields) -> None:
                nonlocal added
                cat = cats[category]
                if (cat.id, name) in existing:
                    return
                db.add(Plan(organization_id=org.id, branch_id=branch.id, category_id=cat.id, name=name, **fields))
                added += 1

            for category, (rows, extra) in MEMBERSHIPS.items():
                for months, price in rows:
                    want(category, MONTHS[months], type=PlanType.MEMBERSHIP, service_type=PlanServiceType.GENERAL,
                         duration_months=months, duration_days=months * 30, price=Decimal(price), total_sessions=0,
                         description=DESCRIPTIONS.get(category), **extra)
            for name, sessions, days, price in PT:
                want("Personal Training", name, type=PlanType.ADD_ON,
                     service_type=PlanServiceType.PERSONAL_TRAINING, duration_days=days, price=Decimal(price),
                     total_sessions=sessions,
                     description=f"{sessions // 4} weeks · {sessions} sessions · valid {days} days")

            if hide_old:
                old = (await db.execute(select(Plan).where(
                    Plan.branch_id == branch.id, Plan.is_delete.is_(False), Plan.is_active.is_(True),
                    or_(Plan.name.ilike("Smoke%"), Plan.name.ilike("Spare%"))))).scalars().all()
                for p in old:
                    p.is_active = False
                    hidden += 1
        await db.commit()
        print(f"added {added} plans, hid {hidden} old plans across {len(branches)} branches")


if __name__ == "__main__":
    asyncio.run(main("--hide-old" in sys.argv))
