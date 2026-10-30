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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if errors:
        first = errors[0]
        field = ".".join(str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")) or "request"
        message = f"{field}: {first.get('msg', 'Invalid value')}"
    else:
        message = "Validation error"
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
    skip_prefixes=["/docs", "/redoc", "/openapi.json"],
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
            if path in _PUBLIC_PATHS:
                operation["security"] = []
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_bearer
