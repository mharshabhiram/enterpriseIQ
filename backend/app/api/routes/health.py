from fastapi import APIRouter
from sqlalchemy import text

from app.ai.health import check_ollama
from app.database import engine

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/ai")
def ai_health() -> dict:
    status = check_ollama()
    return {"reachable": status.reachable, "missing_models": status.missing_models, "message": status.message}
