# Import every model module here so one `import app.models` registers the full
# metadata (app + rbac package) — Alembic autogenerate depends on this.
from rbac.models import (  # noqa: F401
    RBACModule,
    RBACPermission,
    RBACRole,
    RBACRolePermission,
    RBACScreen,
    UserRole,
)

from app.models.attendance import AttendanceDevice, AttendanceSession
from app.models.base import Base, BaseModel, utcnow
from app.models.billing import Offer, Payment, Plan, PlanCategory, Subscription
from app.models.diet import DietPlan, DietPlanItem, FoodItem
from app.models.member import Lead, Member
from app.models.membership import MemberAssessment, MemberDocument, Refund, SubscriptionFreeze
from app.models.organization import Branch, Organization, OrgFile
from app.models.referral import ReferralProgram, ReferralReward, ReferralRewardMember, ReferralTier
from app.models.staff import Attendance, Employee, EmployeeFeedback, Salary
from app.models.training import PTSessionLog, PTSubscription
from app.models.user import User, UserSession

__all__ = [
    "Base", "BaseModel", "utcnow",
    "Organization", "Branch", "User", "UserSession",
    "Member", "Lead", "Plan", "PlanCategory", "Offer", "Subscription", "Payment",
    "PTSubscription", "PTSessionLog",
    "MemberDocument", "SubscriptionFreeze", "Refund", "MemberAssessment",
    "ReferralProgram", "ReferralTier", "ReferralReward", "ReferralRewardMember",
    "Employee", "EmployeeFeedback", "Attendance", "Salary", "AttendanceSession", "AttendanceDevice",
    "FoodItem", "DietPlan", "DietPlanItem",
    "RBACModule", "RBACScreen", "RBACPermission", "RBACRole", "RBACRolePermission", "UserRole",
]
