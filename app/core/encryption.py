# Fernet encrypt/decrypt for PII columns (Aadhaar, PAN, ID-proof, bank account)
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache(maxsize=1)
def _pii_fernet() -> Fernet:
    # Built on first PII read/write, never at import time.
    return Fernet(settings.PII_KEY.encode())


def encrypt_pii(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _pii_fernet().encrypt(value.encode()).decode()


def decrypt_pii(value: str | None) -> str | None:
    if not value:
        return None
    return _pii_fernet().decrypt(value.encode()).decode()


def mask_pii(plain: str | None) -> str | None:
    """XXXX-XXXX-1234 style — only the last 4 characters survive."""
    if not plain:
        return None
    tail = plain[-4:]
    return f"XXXX-XXXX-{tail}"
