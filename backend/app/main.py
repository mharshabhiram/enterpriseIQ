"""
EnterpriseIQ FastAPI application entrypoint.

Wires middleware, routers, and centralized exception handling. Every error
response - whether a domain error we raised on purpose, a Pydantic
validation failure, or an unhandled framework HTTPException - comes back in
the same shape:

    {"error": {"code": "SOME_CODE", "message": "human-readable message"}}

per project brief section 23.
"""
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, chat, documents, search, summaries, users
from app.config import settings
from app.utils.errors import AppError

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
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Catches framework-level errors we didn't raise ourselves (e.g. FastAPI's
    # own 404 for an unmatched route), so the response shape is still consistent.
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
    )


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(summaries.router)
app.include_router(admin.router)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Liveness/readiness probe used by Docker Compose and monitoring."""
    return {"status": "ok", "service": "enterpriseiq-backend", "env": settings.app_env}
