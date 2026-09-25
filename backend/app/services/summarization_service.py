"""
Summarization service (project brief section 12).

Two summarization strategies, chosen automatically by document length:

- DIRECT: if a document's full extracted text fits within the
  MAX_CONTEXT_LENGTH budget (the same budget rag_service uses for RAG
  context - reused deliberately rather than introducing a second "how much
  text can we hand the LLM at once" setting), summarize it in one LLM call.
- MAP-REDUCE: otherwise, split the chunks into groups that each fit the
  budget, summarize each group independently (MAP), then combine those
  partial summaries into one final summary (REDUCE). This is one level of
  map-reduce - if the combined partial summaries *themselves* exceed the
  budget (an extremely large document), they're truncated defensively
  rather than recursing indefinitely; a second reduce pass is a reasonable
  future improvement for that edge case, not attempted here.

`summarize_chunks` is the reusable primitive (used directly by
comparison_service too, for summarizing each side of a large comparison);
`summarize_document` adds the RBAC-checked document lookup on top.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.ai.llm_provider import LLMProvider
from app.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.enums import ProcessingStatus
from app.repositories import document_chunk_repository
from app.schemas.summary import SummaryType
from app.services import document_service
from app.utils.errors import InvalidOperationError

_SUMMARY_TYPE_INSTRUCTIONS = {
    SummaryType.SHORT: (
        "Write a very concise summary in 2-3 sentences capturing only the most essential point(s)."
    ),
    SummaryType.DETAILED: (
        "Write a thorough, detailed summary covering all significant points, organized into clear paragraphs."
    ),
    SummaryType.EXECUTIVE: (
        "Write an executive summary for busy decision-makers: lead with the most important takeaways, "
        "decisions, or action items, in a concise business tone."
    ),
}

_MAP_INSTRUCTION = (
    "Extract and list the key points, facts, and important details from the following excerpt of a "
    "larger document. Be factual and concise - this will be combined with summaries of other excerpts "
    "from the same document later, so do not add commentary or try to summarize the whole document."
)


@dataclass
class SummaryResult:
    document: Document
    summary_type: SummaryType
    summary: str
    chunk_count: int
    map_reduce_used: bool


def _group_chunks_by_budget(chunks: List[DocumentChunk], budget: int) -> List[List[DocumentChunk]]:
    groups: List[List[DocumentChunk]] = []
    current_group: List[DocumentChunk] = []
    current_length = 0

    for chunk in chunks:
        chunk_length = len(chunk.chunk_text)
        if current_group and current_length + chunk_length > budget:
            groups.append(current_group)
            current_group = []
            current_length = 0
        current_group.append(chunk)
        current_length += chunk_length

    if current_group:
        groups.append(current_group)
    return groups


async def _summarize_directly(
    provider: LLMProvider, chunks: List[DocumentChunk], summary_type: SummaryType
) -> str:
    text = "\n\n".join(chunk.chunk_text for chunk in chunks)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that summarizes internal organizational documents. "
                f"{_SUMMARY_TYPE_INSTRUCTIONS[summary_type]} Base your summary only on the provided text."
            ),
        },
        {"role": "user", "content": f"Document content:\n\n{text}"},
    ]
    return await provider.generate(messages)


async def _summarize_map_reduce(
    provider: LLMProvider, chunks: List[DocumentChunk], summary_type: SummaryType
) -> str:
    groups = _group_chunks_by_budget(chunks, settings.max_context_length)

    partial_summaries = []
    for group in groups:
        group_text = "\n\n".join(chunk.chunk_text for chunk in group)
        messages = [
            {"role": "system", "content": _MAP_INSTRUCTION},
            {"role": "user", "content": group_text},
        ]
        partial_summaries.append(await provider.generate(messages))

    combined = "\n\n".join(f"Excerpt summary {i + 1}:\n{s}" for i, s in enumerate(partial_summaries))
    if len(combined) > settings.max_context_length:
        # Very large document: bounded truncation rather than a second recursive
        # reduce pass - documented as a known limitation (see README).
        combined = combined[: settings.max_context_length]

    messages = [
        {
            "role": "system",
            "content": (
                "You are combining summaries of sequential sections of one document into a single, "
                f"cohesive summary. {_SUMMARY_TYPE_INSTRUCTIONS[summary_type]}"
            ),
        },
        {"role": "user", "content": combined},
    ]
    return await provider.generate(messages)


async def summarize_chunks(
    provider: LLMProvider, chunks: List[DocumentChunk], summary_type: SummaryType
) -> Tuple[str, bool]:
    """Returns (summary_text, map_reduce_used)."""
    total_length = sum(len(chunk.chunk_text) for chunk in chunks)
    if total_length <= settings.max_context_length:
        return await _summarize_directly(provider, chunks, summary_type), False
    return await _summarize_map_reduce(provider, chunks, summary_type), True


async def summarize_document(
    session: AsyncSession,
    actor,
    document_id,
    summary_type: SummaryType,
    *,
    llm_provider: Optional[LLMProvider] = None,
) -> SummaryResult:
    document = await document_service.get_document(session, actor, document_id)
    if document.processing_status != ProcessingStatus.COMPLETED:
        raise InvalidOperationError(
            "This document has not finished processing yet and cannot be summarized."
        )

    chunks = await document_chunk_repository.list_for_document_ordered(session, document.id)
    if not chunks:
        raise InvalidOperationError("This document has no extracted content to summarize.")

    provider = llm_provider or get_llm_provider()
    summary_text, map_reduce_used = await summarize_chunks(provider, chunks, summary_type)

    return SummaryResult(
        document=document,
        summary_type=summary_type,
        summary=summary_text,
        chunk_count=len(chunks),
        map_reduce_used=map_reduce_used,
    )
