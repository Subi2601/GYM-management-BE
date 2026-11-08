"""Idempotent seed — RBAC catalogue, demo organization + logins, food catalogue, demo plans.

Run:  python -m app.utils.seed
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from rbac.models import RBACModule, RBACPermission, RBACRole, RBACRolePermission, RBACScreen, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.enums import AccountRole, FoodCategory, PlanServiceType, PlanType
from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.models.billing import Plan, PlanCategory
from app.models.diet import FoodItem
from app.models.organization import Branch, Organization
from app.models.user import User
from app.services.plan_category_service import DEFAULT_CATEGORIES
from app.services.role_service import RoleService
from app.utils.rbac_catalog import CATALOG, LEGACY_ROLE_MAP

_log = logging.getLogger("seed")

FOODS = [
    # name, category, kcal, protein, carbs, fats, unit, benefits — per 100 g / serving unit
    ("Oats (Cooked)", "VEG", 68.0, 2.4, 12.0, 1.4, "grams", "Rich in fiber and complex carbs"),
    ("Whole Egg (Boiled)", "NON_VEG", 155.0, 13.0, 1.1, 11.0, "pieces", "Excellent source of high-quality protein"),
    ("Idli (2 pieces)", "VEG", 120.0, 4.0, 24.0, 0.5, "pieces", "Light and easy to digest"),
    ("Bread (Whole Wheat)", "VEG", 265.0, 9.0, 43.0, 3.2, "slices", "Good source of whole grains"),
    ("Greek Yogurt", "VEG", 59.0, 10.0, 3.6, 0.4, "grams", "High in protein and probiotics"),
    ("Chicken Breast (Grilled)", "NON_VEG", 165.0, 31.0, 0.0, 3.6, "grams", "Lean protein source"),
    ("Brown Rice (Cooked)", "VEG", 111.0, 2.6, 23.0, 0.9, "grams", "Complex carbs for sustained energy"),
    ("Paneer (Cottage Cheese)", "VEG", 265.0, 18.0, 1.2, 20.0, "grams", "Vegetarian protein source"),
    ("Dal (Lentils)", "VEG", 116.0, 9.0, 20.0, 0.4, "grams", "Plant-based protein and fiber"),
    ("Salad (Mixed Greens)", "VEG", 15.0, 1.0, 3.0, 0.0, "bowl", "Essential vitamins and minerals"),
    ("Fish (Grilled Salmon)", "NON_VEG", 208.0, 20.0, 0.0, 13.0, "grams", "Omega-3 fatty acids"),
    ("Almonds", "VEG", 579.0, 21.0, 22.0, 50.0, "grams", "Healthy fats and Vitamin E"),
    ("Apple", "VEG", 52.0, 0.3, 14.0, 0.2, "pieces", "Fiber-rich fruit"),
    ("Peanut Butter", "VEG", 588.0, 25.0, 20.0, 50.0, "grams", "Protein and healthy fats"),
]

DEMO_PLANS = [
    # name, type, service_type, days, price, sessions
    ("Monthly Membership", PlanType.MEMBERSHIP, PlanServiceType.GENERAL, 30, "1500", 0),
    ("Quarterly Membership", PlanType.MEMBERSHIP, PlanServiceType.GENERAL, 90, "4000", 0),
    ("Annual Membership", PlanType.MEMBERSHIP, PlanServiceType.GENERAL, 365, "12000", 0),
    ("Personal Training - 12 Sessions", PlanType.ADD_ON, PlanServiceType.PERSONAL_TRAINING, 30, "6000", 12),
    ("Diet Plan - Standard", PlanType.ADD_ON, PlanServiceType.DIET, 30, "1000", 0),
    ("Diet Plan - Premium", PlanType.ADD_ON, PlanServiceType.DIET, 30, "2000", 0),
]


async def _first(db: AsyncSession, stmt):
    return (await db.execute(stmt)).scalars().first()


async def seed_rbac(db: AsyncSession) -> None:
    perm_ids: dict[str, object] = {}
    screen_of: dict[str, object] = {}
    for m_code, m_name, icon, m_sort, screens in CATALOG:
        module = await _first(db, select(RBACModule).where(RBACModule.code == m_code))
        if module is None:
            module = RBACModule(code=m_code, name=m_name, icon=icon, sort_order=m_sort)
            db.add(module)
            await db.flush()
        for s_code, s_name, route, s_sort, perms in screens:
            screen = await _first(db, select(RBACScreen).where(RBACScreen.code == s_code))
            if screen is None:
                screen = RBACScreen(module_id=module.id, code=s_code, name=s_name, route_path=route, sort_order=s_sort)
                db.add(screen)
                await db.flush()
            for p_code, p_name in perms:
                perm = await _first(db, select(RBACPermission).where(RBACPermission.code == p_code))
                if perm is None:
                    perm = RBACPermission(screen_id=screen.id, code=p_code, name=p_name)
                    db.add(perm)
                    await db.flush()
                perm_ids[p_code] = perm.id
                screen_of[p_code] = screen.id
    await db.flush()


async def seed_org_roles(db: AsyncSession) -> None:
    """Every gym gets its own Owner / Sub-admin / Manager / Staff roles (access is then the owner's to change);
    logins still on the old shared OWNER / ADMIN / TRAINER roles move onto them and the shared rows retire."""
    roles = RoleService(db)
    for org in (await db.execute(select(Organization).where(Organization.deleted_at.is_(None)))).scalars().all():
        org_roles = await roles.ensure_org_roles(org.id)
        moved = await roles.move_legacy_logins(org.id, org_roles)
        if moved:
            _log.info("%s: moved %d login(s) to the gym's own roles", org.name, moved)
    for legacy in (await db.execute(select(RBACRole).where(RBACRole.organization_id.is_(None),
                                                           RBACRole.deleted_at.is_(None)))).scalars().all():
        for link in (await db.execute(select(UserRole).where(UserRole.role_id == legacy.id,
                                                             UserRole.deleted_at.is_(None)))).scalars():
            link.soft_delete()                 # only the platform superadmin is left here; it bypasses RBAC
        for grant in (await db.execute(select(RBACRolePermission).where(
                RBACRolePermission.role_id == legacy.id, RBACRolePermission.deleted_at.is_(None)))).scalars():
            grant.soft_delete()
        legacy.soft_delete()
        _log.info("retired shared role %s", legacy.code)
    await db.flush()


async def _ensure_user(db: AsyncSession, *, email: str, password: str, name: str, role: AccountRole,
                       org: Organization | None, branch: Branch | None, superadmin: bool = False) -> User:
    user = await _first(db, select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, password_hash=hash_password(password), role=role,
                    organization_id=org.id if org else None, branch_id=branch.id if branch else None,
                    is_superadmin=superadmin)
        db.add(user)
        await db.flush()
        _log.info("created login %s", email)
    if org is None:                            # platform superadmin: no gym role, bypasses RBAC
        return user
    rbac_role = (await RoleService(db).ensure_org_roles(org.id))[LEGACY_ROLE_MAP[role.value]]
    if await _first(db, select(UserRole).where(UserRole.user_id == user.id, UserRole.deleted_at.is_(None))) is None:
        db.add(UserRole(user_id=user.id, role_id=rbac_role.id, assigned_by=user.id))
    return user


async def seed_demo(db: AsyncSession) -> None:
    org = await _first(db, select(Organization).where(Organization.code == "STAG"))
    if org is None:
        org = Organization(name=settings.SEED_ORG_NAME, code="STAG")
        db.add(org)
        await db.flush()
    branches = []
    for name, location in (("Main Branch", "Downtown"), ("North Branch", "North Side")):
        branch = await _first(db, select(Branch).where(Branch.organization_id == org.id, Branch.branch_name == name))
        if branch is None:
            branch = Branch(organization_id=org.id, branch_name=name, location=location)
            db.add(branch)
            await db.flush()
        branches.append(branch)
    main, north = branches

    await _ensure_user(db, email=settings.SEED_OWNER_EMAIL, password=settings.SEED_OWNER_PASSWORD,
                       name="Owner", role=AccountRole.OWNER, org=org, branch=main)
    await _ensure_user(db, email=settings.SEED_TRAINER_EMAIL, password=settings.SEED_TRAINER_PASSWORD,
                       name="Trainer", role=AccountRole.TRAINER, org=org, branch=north)
    await _ensure_user(db, email=settings.SEED_SUPERADMIN_EMAIL, password=settings.SEED_SUPERADMIN_PASSWORD,
                       name="Platform Admin", role=AccountRole.OWNER, org=None, branch=None, superadmin=True)

    if await _first(db, select(PlanCategory).where(PlanCategory.organization_id == org.id)) is None:
        for i, cat_name in enumerate(DEFAULT_CATEGORIES, start=1):
            db.add(PlanCategory(organization_id=org.id, name=cat_name, sort_order=i))
        await db.flush()
    categories = {c.name: c.id for c in (await db.execute(
        select(PlanCategory).where(PlanCategory.organization_id == org.id))).scalars()}

    if await _first(db, select(Plan).where(Plan.organization_id == org.id)) is None:
        for branch in branches:
            for name, ptype, service, days, price, sessions in DEMO_PLANS:
                category = ("Personal Training" if service == PlanServiceType.PERSONAL_TRAINING
                            else "Diet" if service == PlanServiceType.DIET else "General")
                db.add(Plan(organization_id=org.id, branch_id=branch.id, name=name, type=ptype,
                            service_type=service, duration_days=days, price=Decimal(price),
                            total_sessions=sessions, category_id=categories[category],
                            duration_months={30: 1, 90: 3, 365: 12}.get(days) if ptype == PlanType.MEMBERSHIP
                            else None))

    if await _first(db, select(FoodItem).where(FoodItem.organization_id.is_(None))) is None:
        for name, cat, kcal, protein, carbs, fats, unit, benefits in FOODS:
            db.add(FoodItem(name=name, category=FoodCategory(cat), calories=kcal, protein=protein, carbs=carbs,
                            fats=fats, serving_unit=unit, nutritional_benefits=benefits))


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed_rbac(db)
        await seed_demo(db)
        await seed_org_roles(db)
        await db.commit()
    _log.info("seed complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
