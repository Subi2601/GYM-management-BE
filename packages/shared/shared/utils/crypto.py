import hashlib
import hmac
import secrets

import bcrypt

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """bcrypt hash at cost 12. Plaintext never stored."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def sha256_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def generate_secure_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
