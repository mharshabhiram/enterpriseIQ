import json
import uuid

from sqlalchemy.orm import Session

from app.ai.base import ChatMessage, EmbeddingProvider, LLMProvider
from app.ai.prompts import COMPARISON_SYSTEM_PROMPT
from app.exceptions import AppError, LLMUnavailable
from app.models import User
from app.schemas.document import CompareResponse
from app.schemas.search import SearchFilters
from app.services.audit_service import AuditAction, record
from app.services.retrieval_service import RetrievalService
from app.services.summarization_service import SummarizationService, document_text

BUDGET = 9000  # characters of material per document sent to the model


class ComparisonService:
    def __init__(self, db: Session, llm: LLMProvider, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.llm = llm
        self.retrieval = RetrievalService(db, embedder)
        self.summarizer = SummarizationService(db, llm)

    def _material(self, user: User, document_id: uuid.UUID, focus: str | None) -> tuple[str, str]:
        title, text = document_text(self.db, user, document_id)  # enforces access
        if len(text) <= BUDGET:
            return title, text
        if focus:  # retrieve only the parts of this document relevant to the focus
            chunks = self.retrieval.retrieve(user, focus, top_k=14, threshold=0.2, filters=SearchFilters(document_ids=[document_id]))
            if chunks:
                ordered = sorted(chunks, key=lambda c: c.page or 0)
                return title, "\n\n".join(f"(p. {c.page}) {c.text}" if c.page else c.text for c in ordered)[:BUDGET]
        notes, _ = self.summarizer.condense(title, text)
        return title, notes[:BUDGET]

    def compare(self, user: User, a_id: uuid.UUID, b_id: uuid.UUID, focus: str | None) -> CompareResponse:
        if a_id == b_id:
            raise AppError("Pick two different documents.", code="SAME_DOCUMENT")
        title_a, text_a = self._material(user, a_id, focus)
        title_b, text_b = self._material(user, b_id, focus)
        focus_line = f"Focus on: {focus}\n\n" if focus else ""
        prompt = f'{focus_line}DOCUMENT A: "{title_a}"\n{text_a}\n\n=====\n\nDOCUMENT B: "{title_b}"\n{text_b}'
        raw = self.llm.generate([ChatMessage("system", COMPARISON_SYSTEM_PROMPT), ChatMessage("user", prompt)], json_mode=True)
        try:
            data = json.loads(raw)
            result = CompareResponse(
                document_a=title_a,
                document_b=title_b,
                overview=data.get("overview", ""),
                key_differences=data.get("key_differences", []),
                categories=data.get("categories", []),
            )
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            raise LLMUnavailable("The model returned an invalid comparison. Please try again.") from exc
        record(self.db, AuditAction.COMPARISON_GENERATED, user.id, "document", a_id, {"other": str(b_id), "focus": focus})
        return result
