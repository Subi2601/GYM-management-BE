"""RBAC catalogue — Module → Screen → Permission tree and default role grants.

Routers only ever reference these permission codes through @require_permission; roles are data.
"""
from __future__ import annotations

# (module_code, module_name, icon, sort, [(screen_code, screen_name, route, sort, [(perm_code, perm_name)])])
CATALOG: list[tuple] = [
    ("dashboard", "Dashboard", "layout-dashboard", 10, [
        ("dashboard", "Dashboard", "/dashboard", 10, [("dashboard:view", "View dashboard")]),
    ]),
    ("organization", "Organization", "building", 20, [
        ("branches", "Branches", "/branches", 10, [
            ("branch:list", "List branches"), ("branch:create", "Create branch"),
            ("branch:update", "Update branch"), ("branch:delete", "Delete branch"),
            ("branch:switch", "Switch between branches"),
        ]),
        ("roles", "Roles & Access", "/roles", 20, [
            ("role:list", "View roles & access"), ("role:manage", "Create roles and set what they can do"),
        ]),
        ("gym_settings", "Gym Settings", "/gym-settings", 25, [
            ("gym:manage", "Change the gym profile: name, logo, contacts, GSTIN, terms & conditions"),
        ]),
        ("settings", "Configuration", "/configuration", 30, [
            ("setting:manage", "Change configuration (trial class, freeze / refund rules, renewal days, late grace)"),
        ]),
    ]),
    ("members", "Members", "users", 30, [
        ("members", "Members", "/members", 10, [
            ("member:list", "List members"), ("member:create", "Register member"),
            ("member:update", "Update member"), ("member:delete", "Delete member"),
        ]),
        ("leads", "Leads", "/leads", 20, [
            ("lead:list", "List leads"), ("lead:create", "Create lead"), ("lead:update", "Update lead"),
            ("lead:delete", "Delete lead"), ("lead:convert", "Convert lead to member"),
        ]),
        ("referrals", "Referrals", "/referrals", 25, [
            ("referral:list", "View referrals, rewards and referral trees"),
            ("referral:manage", "Set the monthly referral reward and give rewards"),
        ]),
        ("subscriptions", "Subscriptions", "/subscriptions", 30, [
            ("subscription:list", "List subscriptions"), ("subscription:create", "Create / renew subscription"),
            ("membership:manage", "Freeze, transfer, cancel & refund memberships"),
        ]),
    ]),
    ("plans", "Plans", "calendar", 40, [
        ("plans", "Plans", "/plans", 10, [
            ("plan:list", "List plans"), ("plan:create", "Create plan"),
            ("plan:update", "Update plan"), ("plan:delete", "Delete plan"),
        ]),
        ("offers", "Offers", "/offers", 20, [
            ("offer:list", "View offers"), ("offer:manage", "Create / edit / switch offers on or off"),
        ]),
    ]),
    ("finance", "Accounts & Finance", "indian-rupee", 50, [
        ("payments", "Payments", "/payments", 10, [
            ("payment:list", "List payments"), ("payment:create", "Record payment"),
            ("payment:stats", "Collection statistics"), ("payment:invoice", "View / print invoice"),
        ]),
    ]),
    ("training", "Personal Training", "dumbbell", 60, [
        ("personal_training", "Personal Training", "/personal-training", 10, [
            ("pt:list", "List PT clients"), ("pt:create", "Subscribe member to PT"),
            ("pt:update", "Change trainer"), ("pt:log", "Log PT session"),
        ]),
    ]),
    ("diet", "Diet Plans", "salad", 70, [
        ("diet_plans", "Diet Plans", "/diet-plans", 10, [
            ("diet:list", "View diet plans"), ("diet:manage", "Build / edit diet plans"),
            ("food:list", "View food catalogue"), ("food:manage", "Manage food catalogue"),
        ]),
    ]),
    ("staff", "Staff", "id-card", 80, [
        ("staff", "Staff Management", "/staff", 10, [
            ("employee:list", "List staff"), ("employee:create", "Add staff"),
            ("employee:update", "Update staff"), ("employee:terminate", "Terminate staff"),
            ("feedback:create", "Add client feedback"), ("pii:view", "View Aadhaar / PAN / bank numbers"),
            ("employee:login", "Give staff app logins, reset their passwords"),
        ]),
        ("attendance", "Attendance", "/attendance", 20, [
            ("attendance:list", "View attendance"), ("attendance:mark", "Mark attendance / checkout"),
            ("attendance:qr", "Manage attendance QR codes, gym location and linked phones"),
        ]),
        ("payroll", "Payroll & Salary", "/salary", 30, [
            ("salary:list", "View payroll"), ("salary:calculate", "Calculate salary"),
            ("salary:pay", "Record salary payment"),
        ]),
    ]),
    ("account", "Account", "user", 90, [
        ("profile", "My Account", None, 10, [("auth:me", "View own profile")]),
    ]),
]

ALL_PERMISSIONS = [p for _, _, _, _, screens in CATALOG for *_, perms in screens for p, _ in perms]

# ── Role hierarchy ──────────────────────────────────────────────────────────────────────────────────────
# Every gym (organization) gets its own copy of these roles. `level` orders them: a user may only create, edit
# or hand out roles below their own level. Owner > Sub-admin (all branches) > Manager > Staff (one branch).
OWNER_LEVEL, SUB_ADMIN_LEVEL, MANAGER_LEVEL, STAFF_LEVEL = 100, 80, 50, 10
# Roles at this level or above see every branch ("All Branches"); below it a login is fixed to its branch.
ALL_BRANCHES_LEVEL = SUB_ADMIN_LEVEL

# Control of the gym itself stays with the owner: never grantable to another role.
OWNER_ONLY = {"role:list", "role:manage", "branch:create", "branch:delete"}
# Only all-branch roles may switch branches.
ALL_BRANCHES_ONLY = {"branch:switch"}

_STAFF = [
    "auth:me",
    "member:list", "member:create", "member:update",
    "lead:list", "lead:create", "lead:update", "lead:convert",
    "referral:list",
    "subscription:list", "subscription:create",
    "plan:list", "offer:list",
    "payment:create", "payment:invoice",
    "pt:list", "pt:log",
    "diet:list", "food:list",
    "feedback:create",
    "attendance:list", "attendance:mark",
]
# A manager runs one branch: staff work + its sales & finance, staff and attendance (no payroll, PII, pricing).
_MANAGER = _STAFF + [
    "dashboard:view",
    "member:delete", "lead:delete",
    "payment:list", "payment:stats",
    "pt:create", "pt:update",
    "membership:manage", "referral:manage",
    "diet:manage", "food:manage",
    "employee:list", "employee:create", "employee:update", "employee:terminate", "employee:login",
    "attendance:qr",
]

# code: (name, description, level, default grants) — grants are seeded only when a gym's role is first created.
ROLES: dict[str, tuple[str, str, int, list[str]]] = {
    "OWNER": ("Owner", "Super admin: the whole gym, every branch. Always has full access", OWNER_LEVEL,
              ALL_PERMISSIONS),
    "SUB_ADMIN": ("Sub-admin", "Owner's helper: every branch and screen, but not roles & access or adding / removing "
                  "branches", SUB_ADMIN_LEVEL, [p for p in ALL_PERMISSIONS if p not in OWNER_ONLY]),
    "MANAGER": ("Manager", "Runs one branch: members, leads, staff, sales & finance of that branch", MANAGER_LEVEL,
                _MANAGER),
    "STAFF": ("Staff", "Front desk / trainer of one branch: members and leads, collects payments", STAFF_LEVEL,
              _STAFF),
}
OWNER_ROLE = "OWNER"
# Old fixed login kinds → the role a gym's existing logins move to.
LEGACY_ROLE_MAP = {"OWNER": "OWNER", "ADMIN": "MANAGER", "TRAINER": "STAFF"}
