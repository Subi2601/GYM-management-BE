"""Router registry — main.py mounts every router listed here."""
from app.api.v1.assessments import router as assessments_router
from app.api.v1.attendance import router as attendance_router
from app.api.v1.auth import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.checkin import invoice_router as public_invoice_router
from app.api.v1.checkin import router as checkin_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.diet import router as diet_router
from app.api.v1.employees import router as employees_router
from app.api.v1.enquiry import public_router as public_enquiry_router
from app.api.v1.enquiry import router as enquiry_link_router
from app.api.v1.foods import router as foods_router
from app.api.v1.gym_profile import public_router as public_gym_router
from app.api.v1.gym_profile import router as gym_profile_router
from app.api.v1.leads import router as leads_router
from app.api.v1.members import router as members_router
from app.api.v1.memberships import refunds_router
from app.api.v1.memberships import router as memberships_router
from app.api.v1.offers import router as offers_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.payments import router as payments_router
from app.api.v1.plan_categories import router as plan_categories_router
from app.api.v1.plans import router as plans_router
from app.api.v1.referrals import router as referrals_router
from app.api.v1.renewals import router as renewals_router
from app.api.v1.roles import router as roles_router
from app.api.v1.salary import router as salary_router
from app.api.v1.settings import router as settings_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.training import router as training_router

ROUTERS = [
    auth_router,
    organizations_router,
    branches_router,
    roles_router,
    settings_router,
    gym_profile_router,
    public_gym_router,
    members_router,
    assessments_router,
    referrals_router,
    enquiry_link_router,          # before leads: /leads/enquiry-form is not a lead id
    leads_router,
    plan_categories_router,
    plans_router,
    offers_router,
    subscriptions_router,
    memberships_router,
    renewals_router,
    refunds_router,
    payments_router,
    training_router,
    employees_router,
    attendance_router,
    checkin_router,
    public_invoice_router,
    public_enquiry_router,
    salary_router,
    foods_router,
    diet_router,
    dashboard_router,
]
