"""Generate a JWT secret and a PII key for a fresh .env.

    python -m scripts.gen_dev_secrets

Prints the two lines to paste into .env. Generate them once per environment: changing PII_KEY
later makes Aadhaar / PAN / bank numbers already in the database unreadable.
"""
import secrets

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"PII_KEY={Fernet.generate_key().decode()}")
