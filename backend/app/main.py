"""
EnterpriseIQ FastAPI application entrypoint.

Wires middleware, routers, and centralized exception handling. Every error
response - whether a domain error we raised on purpose, a Pydantic
validation failure, a rate-limit rejection, or an unhandled bug - comes
back in the same shape:

    {"error": {"code": "SOME_CODE", "message": "human-readable message"}}

per project brief section 23.
"""
import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import admin, auth, chat, dashboard, documents, search, summaries, users
from app.config import settings
from app.security.rate_limit import limiter
from app.utils.errors import AppError

logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRET_MIN_LENGTH = 32
_PLACEHOLDER_SECRET_PREFIXES = ("change-me", "replace-", "replace_", "your-", "example", "changeme")


def _validate_production_config() -> None:
    """
    Refuse to boot with a missing, placeholder-looking, or too-short JWT
    secret outside local development - a misconfigured deployment silently
    running with a placeholder value (including the literal one shipped in
    .env.example) would completely undermine authentication, and failing
    fast at startup is far better than discovering it later. Checks a
    pattern/length heuristic rather than one exact string, since any
    placeholder-shaped value is equally insecure.
    """
    if settings.app_env == "development":
        return

    secret = settings.jwt_secret_key
    looks_like_placeholder = not secret or secret.lower().startswith(_PLACEHOLDER_SECRET_PREFIXES)
    too_short = len(secret) < _INSECURE_JWT_SECRET_MIN_LENGTH

    if looks_like_placeholder or too_short:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing, looks like a placeholder, or is shorter than "
            f"{_INSECURE_JWT_SECRET_MIN_LENGTH} characters. Set a real, random secret "
            "in the environment before running with APP_ENV != development."
        )


_validate_production_config()

app = FastAPI(
    title="EnterpriseIQ API",
    description="AI-powered enterprise knowledge management system (RAG).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (project brief section 22). A generous global default
# (see app.security.rate_limit) applies to every route via this middleware;
# auth.py applies stricter limits to login/register specifically.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic's default body is a list of per-field errors; we keep that
    # detail but nest it under the same {"error": {...}} envelope as every
    # other error in the API.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields failed validation.",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": f"Rate limit exceeded: {exc.detail}"}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Catches framework-level errors we didn't raise ourselves (e.g. FastAPI's
    # own 404 for an unmatched route), so the response shape is still consistent.
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last resort for genuine bugs (AttributeError, KeyError, an unexpected
    library exception, ...) that weren't deliberately raised as an AppError.
    Always logs the full traceback server-side; only includes the actual
    exception details in the response when DEBUG is on (local development),
    never in a production-configured deployment.
    """
    logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
    message = "An unexpected error occurred."
    if settings.debug:
        message = f"{message} ({type(exc).__name__}: {exc})"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": message}},
    )


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(chat.conversations_router)
app.include_router(dashboard.router)
app.include_router(summaries.router)
app.include_router(admin.router)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Liveness/readiness probe used by Docker Compose and monitoring."""
    return {"status": "ok", "service": "enterpriseiq-backend", "env": settings.app_env}
