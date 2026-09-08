"""
Admin routes.

Scaffolding only (Phase 1). Endpoints are implemented in later phases:
- auth, users            -> Phase 3 (Authentication & RBAC)
- documents, search      -> Phase 4-5 (Document processing, pgvector search)
- chat                   -> Phase 6-7 (RAG Q&A, conversations)
- summaries (documents)  -> Phase 8 (Summarization & comparison)
- admin                  -> Phase 9 (Admin panel)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/admin", tags=["admin"])
