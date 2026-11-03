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
        ("subscriptions", "Subscriptions", "/subscriptions", 30, [
            ("subscription:list", "List subscriptions"), ("subscription:create", "Create / renew subscription"),
        ]),
    ]),
    ("plans", "Plans", "calendar", 40, [
        ("plans", "Plans", "/plans", 10, [
            ("plan:list", "List plans"), ("plan:create", "Create plan"),
            ("plan:update", "Update plan"), ("plan:delete", "Delete plan"),
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

# Default role grants. OWNER/ADMIN get everything; TRAINER mirrors what the original app let trainers do
# (no dashboard, branch management, accounts, payroll, diet, PII).
ROLES: dict[str, tuple[str, str, list[str]]] = {
    "OWNER": ("Owner", "Gym owner — full access to every branch", ALL_PERMISSIONS),
    "ADMIN": ("Admin", "Branch administrator — full access", ALL_PERMISSIONS),
    "TRAINER": ("Trainer", "Floor trainer — fixed to one branch", [
        "auth:me",
        "member:list", "member:create", "member:update", "member:delete",
        "lead:list", "lead:create", "lead:update", "lead:delete", "lead:convert",
        "subscription:list", "subscription:create",
        "plan:list", "plan:create", "plan:update", "plan:delete",
        "payment:create", "payment:invoice",
        "pt:list", "pt:create", "pt:update", "pt:log",
        "employee:list", "employee:create", "employee:update", "employee:terminate", "feedback:create",
        "attendance:list", "attendance:mark",
        "food:list",
    ]),
}
