"""EnterpriseIQ API entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import func, select

from app.ai.health import wait_for_ollama
from app.api.routes import admin, auth, chat, documents, health, search, users
from app.config import get_settings
from app.database import SessionLocal
from app.exceptions import register_exception_handlers
from app.logging_config import configure_logging, get_logger
from app.models import Document, DocumentStatus
from app.security.rate_limit import limiter

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("startup")


def startup_checks() -> None:
    status = wait_for_ollama(settings.ollama_startup_wait_seconds)
    if status.reachable and not status.missing_models:
        log.info("ollama_ready", llm=settings.ollama_llm_model, embeddings=settings.ollama_embedding_model)
    else:
        # Don't crash: the API stays up and AI endpoints return a clear 503 until models are pulled.
        log.warning("ollama_not_ready", message=status.message)
    with SessionLocal() as db:
        stale = db.scalar(
            select(func.count(Document.id)).where(
                Document.processing_status == DocumentStatus.COMPLETED,
                Document.embedding_model != settings.ollama_embedding_model,
            )
        )
        if stale:
            log.warning(
                "embedding_model_changed",
                stale_documents=stale,
                message="Documents embedded with another model are excluded from search. POST /api/admin/reembed to re-process them.",
            )


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    try:
        startup_checks()
    except Exception as exc:  # noqa: BLE001
        log.error("startup_check_failed", error=str(exc))
    yield


app = FastAPI(
    title="EnterpriseIQ API",
    version="1.0.0",
    description="Retrieval-augmented enterprise knowledge management with RBAC. Runs fully on local models via Ollama.",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_exception_handlers(app)

for router in (health.router, auth.router, users.router, documents.router, search.router, chat.router, admin.router):
    app.include_router(router)
