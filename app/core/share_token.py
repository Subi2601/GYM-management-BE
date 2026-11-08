"""Unguessable links for documents shared outside the app (invoice sent on WhatsApp).

token = <uuid hex><first 24 hex of HMAC-SHA256(JWT_SECRET, "<kind>:<uuid hex>")> — no DB lookup to verify, nothing
to store, and a token for one kind (e.g. "invoice") never opens another. Rotating JWT_SECRET revokes all links.
"""
from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from app.config import settings

_SIG_LEN = 24


def _sig(kind: str, hex_id: str) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), f"{kind}:{hex_id}".encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]


def sign(kind: str, obj_id: UUID) -> str:
    return f"{obj_id.hex}{_sig(kind, obj_id.hex)}"


def verify(kind: str, token: str) -> UUID | None:
    if len(token) != 32 + _SIG_LEN:
        return None
    hex_id, sig = token[:32], token[32:]
    if not hmac.compare_digest(sig, _sig(kind, hex_id)):
        return None
    try:
        return UUID(hex=hex_id)
    except ValueError:
        return None
