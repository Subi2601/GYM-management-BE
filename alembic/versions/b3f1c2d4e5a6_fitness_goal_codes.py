"""fitness goal codes: lead / member / PT goal free text -> FitnessGoal codes

Revision ID: b3f1c2d4e5a6
Revises: 6246f359102a
Create Date: 2026-11-03 10:00:00

Data only — the columns stay VARCHAR (the model uses a non-native enum). Known phrases map to their code,
any other non-empty text becomes OTHER so every stored value is a valid FitnessGoal.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3f1c2d4e5a6"
down_revision: Union[str, None] = "6246f359102a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODES = ("WEIGHT_LOSS", "MUSCLE_GAIN", "BODY_TONING", "WEIGHT_GAIN", "STRENGTH", "ENDURANCE",
         "SPORTS_PERFORMANCE", "COMPETITION_PREP", "GENERAL_FITNESS", "FLEXIBILITY", "REHAB",
         "MEDICAL_CONDITION", "PRE_POST_NATAL", "SENIOR_FITNESS", "STRESS_RELIEF", "OTHER")

# lower(trim(text)) LIKE pattern -> code; first match wins
PHRASES = (
    ("%weight loss%", "WEIGHT_LOSS"), ("%fat loss%", "WEIGHT_LOSS"), ("%slim%", "WEIGHT_LOSS"),
    ("%muscle%", "MUSCLE_GAIN"), ("%bulk%", "MUSCLE_GAIN"),
    ("%toning%", "BODY_TONING"), ("%tone%", "BODY_TONING"),
    ("%weight gain%", "WEIGHT_GAIN"),
    ("%strength%", "STRENGTH"), ("%power%", "STRENGTH"),
    ("%endurance%", "ENDURANCE"), ("%stamina%", "ENDURANCE"), ("%cardio%", "ENDURANCE"),
    ("%fitness%", "GENERAL_FITNESS"), ("%health%", "GENERAL_FITNESS"),
    ("%flexib%", "FLEXIBILITY"), ("%mobility%", "FLEXIBILITY"),
)

LABELS = {"WEIGHT_LOSS": "Weight loss", "MUSCLE_GAIN": "Muscle gain", "BODY_TONING": "Body toning",
          "WEIGHT_GAIN": "Weight gain", "STRENGTH": "Strength", "ENDURANCE": "Endurance",
          "SPORTS_PERFORMANCE": "Sports performance", "COMPETITION_PREP": "Competition prep",
          "GENERAL_FITNESS": "General fitness", "FLEXIBILITY": "Flexibility", "REHAB": "Injury rehab",
          "MEDICAL_CONDITION": "Medical condition", "PRE_POST_NATAL": "Pre / post natal",
          "SENIOR_FITNESS": "Senior fitness", "STRESS_RELIEF": "Stress relief", "OTHER": "Other"}

COLUMNS = (("lead_leads", "goal"), ("member_members", "fitness_goal"), ("pt_subscriptions", "goal"))


def upgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in CODES)
    for table, col in COLUMNS:
        op.execute(f"UPDATE {table} SET {col} = NULL WHERE trim({col}) = ''")
        for pattern, code in PHRASES:
            op.execute(f"UPDATE {table} SET {col} = '{code}' "
                       f"WHERE {col} NOT IN ({codes}) AND lower(trim({col})) LIKE '{pattern}'")
        op.execute(f"UPDATE {table} SET {col} = 'OTHER' WHERE {col} IS NOT NULL AND {col} NOT IN ({codes})")


def downgrade() -> None:
    for table, col in COLUMNS:
        for code, label in LABELS.items():
            op.execute(f"UPDATE {table} SET {col} = '{label}' WHERE {col} = '{code}'")
