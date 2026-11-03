"""Single enum registry — never define an enum in a model, schema, router or controller."""
import enum


class AccountRole(str, enum.Enum):
    """Login role of an operator account — mirrors the rbac_roles code assigned at creation.
    Authorization itself is RBAC-driven (permissions), never by branching on this value."""
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    TRAINER = "TRAINER"


class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class MemberStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"


class MembershipState(str, enum.Enum):
    """Derived from the member's latest subscription — never stored."""
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"     # ends within 7 days
    EXPIRED = "EXPIRED"
    NO_PLAN = "NO_PLAN"


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    FOLLOW_UP = "FOLLOW_UP"
    JOINED = "JOINED"
    NOT_INTERESTED = "NOT_INTERESTED"
    JOINED_ELSEWHERE = "JOINED_ELSEWHERE"


class FitnessGoal(str, enum.Enum):
    """Primary goal of a lead / member, as a coach groups clients for programming and follow-ups.
    Stored as VARCHAR (non-native enum), so options can be added without a DB type change."""
    # Body composition
    WEIGHT_LOSS = "WEIGHT_LOSS"              # fat loss / slimming
    MUSCLE_GAIN = "MUSCLE_GAIN"              # hypertrophy, bulking
    BODY_TONING = "BODY_TONING"              # recomposition: lose fat, firm up
    WEIGHT_GAIN = "WEIGHT_GAIN"              # underweight clients gaining healthy mass
    # Performance
    STRENGTH = "STRENGTH"                    # strength / powerlifting
    ENDURANCE = "ENDURANCE"                  # stamina, cardio, running
    SPORTS_PERFORMANCE = "SPORTS_PERFORMANCE"
    COMPETITION_PREP = "COMPETITION_PREP"    # bodybuilding / physique shows
    # Health & lifestyle
    GENERAL_FITNESS = "GENERAL_FITNESS"
    FLEXIBILITY = "FLEXIBILITY"              # mobility, posture
    REHAB = "REHAB"                          # injury recovery, back / knee pain
    MEDICAL_CONDITION = "MEDICAL_CONDITION"  # diabetes, BP, thyroid, PCOS
    PRE_POST_NATAL = "PRE_POST_NATAL"
    SENIOR_FITNESS = "SENIOR_FITNESS"
    STRESS_RELIEF = "STRESS_RELIEF"
    OTHER = "OTHER"


class PlanType(str, enum.Enum):
    MEMBERSHIP = "MEMBERSHIP"
    ADD_ON = "ADD_ON"
    CUSTOM = "CUSTOM"         # membership with a day count + per-day rate set per plan (price = days × rate)


# Plan types that give gym access — membership expiry, renewals, dashboard and diet eligibility read these.
MEMBERSHIP_PLAN_TYPES = (PlanType.MEMBERSHIP, PlanType.CUSTOM)


class PlanServiceType(str, enum.Enum):
    """What an add-on unlocks. Replaces the old "plan name contains 'pt' / 'diet'" matching."""
    GENERAL = "GENERAL"
    PERSONAL_TRAINING = "PERSONAL_TRAINING"
    DIET = "DIET"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RenewalState(str, enum.Enum):
    """Derived renewal badge on the subscriptions screen."""
    NONE = "NONE"
    EXPIRING = "EXPIRING"     # ends within 3 days
    EXPIRED = "EXPIRED"


class PaymentStatus(str, enum.Enum):
    """Derived: a subscription is PAID once a payment row covers it."""
    PAID = "PAID"
    PENDING = "PENDING"


class PaymentMode(str, enum.Enum):
    CASH = "CASH"
    UPI = "UPI"
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"


class PTStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class EmployeeRole(str, enum.Enum):
    TRAINER = "TRAINER"
    ADMIN = "ADMIN"
    CLEANER = "CLEANER"
    SERVICE_STAFF = "SERVICE_STAFF"
    MANAGER = "MANAGER"
    OWNER = "OWNER"


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    TERMINATED = "TERMINATED"
    ON_LEAVE = "ON_LEAVE"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    HALF_DAY = "HALF_DAY"
    ON_LEAVE = "ON_LEAVE"


class AttendancePersonType(str, enum.Enum):
    """Who an attendance session / linked phone belongs to — the two tabs of the attendance screen."""
    STAFF = "STAFF"
    MEMBER = "MEMBER"


class AttendanceSource(str, enum.Enum):
    """How a check-in / check-out was recorded."""
    MANUAL = "MANUAL"     # front desk, from the attendance screen
    QR = "QR"             # the person scanned the branch's CHECK IN / CHECK OUT poster


class SalaryStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"


class DietTier(str, enum.Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class DietCategory(str, enum.Enum):
    VEG = "VEG"
    NON_VEG = "NON_VEG"


class MealTime(str, enum.Enum):
    BREAKFAST = "Breakfast"
    LUNCH = "Lunch"
    EVENING_SNACK = "Evening Snack"
    DINNER = "Dinner"


class FoodCategory(str, enum.Enum):
    VEG = "VEG"
    NON_VEG = "NON_VEG"
    VEGAN = "VEGAN"
