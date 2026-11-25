"""Hierarchical (map-reduce) summarisation so long documents are never truncated."""
import re
import uuid

from sqlalchemy.orm import Session

from app.ai.base import ChatMessage, LLMProvider
from app.ai.prompts import MAP_SECTION_PROMPT, SUMMARY_INSTRUCTIONS, SUMMARY_SYSTEM_PROMPT
from app.config import get_settings
from app.exceptions import AppError
from app.models import DocumentStatus, User
from app.repositories.documents import DocumentRepository
from app.schemas.document import SummaryResponse
from app.services.audit_service import AuditAction, record
from app.services.document_service import DocumentService


def split_sections(text: str, size: int) -> list[str]:
    sections: list[str] = []
    current = ""
    for para in re.split(r"\n{2,}", text):
        if len(para) > size:
            if current:
                sections.append(current)
                current = ""
            sections.extend(para[i : i + size] for i in range(0, len(para), size))
            continue
        if current and len(current) + len(para) + 2 > size:
            sections.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current.strip():
        sections.append(current)
    return sections


def document_text(db: Session, user: User, document_id: uuid.UUID) -> tuple[str, str]:
    doc = DocumentService(db).get_for_user(user, document_id)
    if doc.processing_status != DocumentStatus.COMPLETED:
        raise AppError(f'"{doc.title}" has not finished processing yet.', code="DOCUMENT_NOT_READY", status_code=409)
    chunks = DocumentRepository(db).chunks(doc.id)
    return doc.title, "\n\n".join(c.chunk_text for c in chunks)


class SummarizationService:
    def __init__(self, db: Session, llm: LLMProvider) -> None:
        self.db = db
        self.llm = llm
        self.settings = get_settings()

    def condense(self, title: str, text: str) -> tuple[str, int]:
        """Map step (and further reduce levels) until the material fits one prompt."""
        size = self.settings.summary_section_chars
        level_input, sections_processed = text, 0
        while len(level_input) > size:
            sections = split_sections(level_input, size)
            sections_processed += len(sections)
            notes = [
                self.llm.generate(
                    [
                        ChatMessage("system", SUMMARY_SYSTEM_PROMPT),
                        ChatMessage("user", f'{MAP_SECTION_PROMPT}\n\nDocument: "{title}" — part {i + 1} of {len(sections)}\n\n{s}'),
                    ]
                )
                for i, s in enumerate(sections)
            ]
            condensed = "\n\n".join(f"## Part {i + 1}\n{n}" for i, n in enumerate(notes))
            if len(condensed) >= len(level_input):  # safety: never loop forever
                level_input = condensed[:size]
                break
            level_input = condensed
        return level_input, sections_processed

    def summarize(self, user: User, document_id: uuid.UUID, summary_type: str) -> SummaryResponse:
        title, text = document_text(self.db, user, document_id)
        material, sections = self.condense(title, text)
        strategy = "map-reduce" if sections else "single-pass"
        summary = self.llm.generate(
            [
                ChatMessage("system", SUMMARY_SYSTEM_PROMPT),
                ChatMessage("user", f'{SUMMARY_INSTRUCTIONS[summary_type]}\n\nDocument title: "{title}"\n\n{material}'),
            ]
        )
        record(self.db, AuditAction.SUMMARY_GENERATED, user.id, "document", document_id, {"type": summary_type, "strategy": strategy})
        return SummaryResponse(
            document_id=document_id, title=title, type=summary_type, strategy=strategy, sections_processed=max(sections, 1), summary=summary
        )
