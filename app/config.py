# Pydantic Settings — reads .env.
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    # HS256 signing secret for access/refresh tokens.
    JWT_SECRET: str = ""
    # Fernet key for PII columns: Aadhaar, PAN, ID-proof number, bank account number.
    # Changing it makes already-stored PII unreadable.
    PII_KEY: str = ""

    # Gym-local calendar — "today" for attendance, expiry and revenue.
    APP_TIMEZONE: str = "Asia/Kolkata"

    FRONTEND_BASE_URL: str = "http://localhost:5173"
    COOKIE_SECURE: bool = False

    # Idle session timeout — no authenticated request for this long ends the session.
    SESSION_IDLE_TIMEOUT_MINUTES: int = 120

    SEED_ORG_NAME: str = "Stag Fitness"
    SEED_OWNER_EMAIL: str = "owner@gym.com"
    SEED_OWNER_PASSWORD: str = "owner123"
    SEED_TRAINER_EMAIL: str = "trainer@gym.com"
    SEED_TRAINER_PASSWORD: str = "trainer123"
    SEED_SUPERADMIN_EMAIL: str = "superadmin@stag.local"
    SEED_SUPERADMIN_PASSWORD: str = "Super@123"

    class Config:
        env_file = os.environ.get("STAG_ENV_FILE", ".env")
        extra = "ignore"


settings = Settings()
