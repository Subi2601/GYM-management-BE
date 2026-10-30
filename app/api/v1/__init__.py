"""Router registry — main.py mounts every router listed here."""
from app.api.v1.attendance import router as attendance_router
from app.api.v1.auth import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.diet import router as diet_router
from app.api.v1.employees import router as employees_router
from app.api.v1.foods import router as foods_router
from app.api.v1.leads import router as leads_router
from app.api.v1.members import router as members_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.payments import router as payments_router
from app.api.v1.plans import router as plans_router
from app.api.v1.salary import router as salary_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.training import router as training_router

ROUTERS = [
    auth_router,
    organizations_router,
    branches_router,
    members_router,
    leads_router,
    plans_router,
    subscriptions_router,
    payments_router,
    training_router,
    employees_router,
    attendance_router,
    salary_router,
    foods_router,
    diet_router,
    dashboard_router,
]
