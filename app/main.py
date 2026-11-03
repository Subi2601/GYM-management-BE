# FastAPI app factory, middleware, router mount
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import iam_core.decorators  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.openapi.utils import get_openapi  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from iam_core.middleware import AuthMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from app.api.v1 import ROUTERS  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.auth import get_token_manager  # noqa: E402
from app.dependencies import get_db  # noqa: E402

_log = logging.getLogger(__name__)

app = FastAPI(title="Stag Fitness SaaS API", version="1.0.0")


# Every error leaves the API in the standard envelope `{success, status_code, message}`.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "status_code": exc.status_code, "message": exc.detail},
        headers=dict(exc.headers) if exc.headers else None,
    )


# Words kept in capitals when a field name becomes a label ("pan_number" → "PAN number").
_ACRONYMS = {"pan": "PAN", "ifsc": "IFSC", "upi": "UPI", "id": "ID", "pt": "PT"}
# Field names whose plain humanised form reads badly.
_LABELS = {"phone": "Phone number", "dob": "Date of birth", "geofence_m": "Check-in radius (m)",
           "morning_start": "Morning shift start time", "morning_end": "Morning shift end time",
           "evening_start": "Evening shift start time", "evening_end": "Evening shift end time"}


def _field_label(loc: tuple) -> str:
    """Last named part of the error location as a sentence-case label: payment.paid_amount → "Paid amount"."""
    parts = [str(p) for p in loc if p not in ("body", "query", "path") and not isinstance(p, int)]
    if not parts:
        return "Request"
    if parts[-1] in _LABELS:
        return _LABELS[parts[-1]]
    words = [_ACRONYMS.get(w, w) for w in parts[-1].split("_")]
    label = " ".join(words)
    return label[0].upper() + label[1:]


def _num(value: object) -> object:
    """0.0 → 0, 10000000.0 → 10,000,000 (limits read like the UI shows them)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, int) else value


def _mid_sentence(label: str) -> str:
    """"Paid amount" → "paid amount", but "PAN number" stays (leading acronym)."""
    first = label.split(" ", 1)[0]
    return label if first.isupper() and len(first) > 1 else label[0].lower() + label[1:]


def _validation_message(error: dict) -> str:
    """One readable sentence per Pydantic error type — this is what the UI shows in its toast."""
    label, kind, ctx = _field_label(error.get("loc", ())), error.get("type", ""), error.get("ctx") or {}
    if (kind == "missing" or (kind == "string_too_short" and ctx.get("min_length") == 1)
            or (kind.endswith("_type") and error.get("input") is None)):   # null sent for a required field
        return f"{label} is required"
    if kind == "string_too_short":
        return f"{label} must be at least {ctx.get('min_length')} characters"
    if kind == "string_too_long":
        return f"{label} must be at most {ctx.get('max_length')} characters"
    if kind in ("greater_than_equal", "greater_than"):
        return f"{label} must be at least {_num(ctx.get('ge', ctx.get('gt')))}"
    if kind in ("less_than_equal", "less_than"):
        return f"{label} must be at most {_num(ctx.get('le', ctx.get('lt')))}"
    if kind in ("enum", "literal_error"):
        return f"Choose a valid {_mid_sentence(label)}"
    if kind == "value_error":
        # Custom validators (e.g. EmailStr) — drop Pydantic's "Value error, " prefix.
        if "email" in label.lower():
            return "Enter a valid email address"
        return f"{label}: {str(error.get('msg', '')).removeprefix('Value error, ')}"
    if kind.endswith("_parsing") or kind.endswith("_type") or kind == "string_pattern_mismatch":
        return f"Enter a valid {_mid_sentence(label)}"
    return f"{label}: {error.get('msg', 'Invalid value')}"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = _validation_message(errors[0]) if errors else "Validation error"
    return JSONResponse(status_code=422, content={"success": False, "status_code": 422, "message": message})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # Services prevent these where possible; this is the safety net (409, no internals exposed).
    # Log the constraint name only — the DB detail echoes the conflicting values (phone, email = PII).
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    constraint = getattr(cause, "constraint_name", None) or type(cause or exc).__name__
    _log.warning("IntegrityError on %s %s: %s", request.method, request.url.path, constraint)
    return JSONResponse(status_code=409, content={"success": False, "status_code": 409,
                                                  "message": "The request conflicts with existing data."})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"success": False, "status_code": 500,
                                                  "message": "Internal server error"})


_PUBLIC_PATHS = ["/health", "/api/v1/auth/login", "/api/v1/auth/refresh"]

# Middleware (added innermost-first: Auth runs after RequestID/SecurityHeaders/CORS)
app.add_middleware(
    AuthMiddleware,
    token_manager=get_token_manager,  # lazy — secret decrypted on first request
    skip_paths=_PUBLIC_PATHS,
    # /api/v1/public/: QR check-in from members' and staff phones (no login; scoped by the poster token).
    skip_prefixes=["/docs", "/redoc", "/openapi.json", "/api/v1/public/"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_BASE_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# require_permission() resolves its DB session through this override
app.dependency_overrides[iam_core.decorators._get_db] = get_db

for router in ROUTERS:
    app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _openapi_with_bearer():
    """Bearer scheme globally; public endpoints get security:[] to remove the lock."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
    }
    schema["security"] = [{"BearerAuth": []}]
    for path, methods in schema.get("paths", {}).items():
        for operation in methods.values():
            if path in _PUBLIC_PATHS or path.startswith("/api/v1/public/"):
                operation["security"] = []
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_bearer
