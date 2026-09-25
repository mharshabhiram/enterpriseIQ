"""
Comparison service (project brief section 13).

Retrieves both documents' full extracted text and asks the LLM to produce a
*structured* comparison (fixed categories, not freeform prose) so a
frontend can render it categorically rather than parsing paragraphs. The
LLM is instructed to respond with JSON matching an exact shape; the
response is defensively parsed and normalized (see _normalize_comparison)
so a malformed or non-JSON response degrades gracefully instead of
breaking the endpoint - real LLM outputs aren't always perfectly
well-formed, and "Do not use fake/placeholder implementations for core
functionality" doesn't mean pretending the JSON will always be valid.

For large documents, comparing raw full text from both sides in one prompt
isn't feasible (see rag_service/summarization_service for the same
MAX_CONTEXT_LENGTH budget concept) - deliberately reuses
summarization_service.summarize_chunks to first summarize each document,
then compares the *summaries* instead of raw text. This keeps the
important content while fitting the budget.
"""
import json
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.ai.llm_provider import LLMProvider
from app.config import settings
from app.models.document import Document
from app.models.enums import ProcessingStatus
from app.repositories import document_chunk_repository
from app.schemas.summary import SummaryType
from app.services import document_service, summarization_service
from app.utils.errors import InvalidOperationError

# Fixed, known category set (project brief section 13's example categories)
# rather than letting the LLM invent arbitrary category names - guarantees
# predictable, always-present output a frontend can render without
# defensive branching for missing/unexpected categories.
COMPARISON_CATEGORIES = [
    "Policy Changes",
    "Dates",
    "Responsibilities",
    "Eligibility",
    "Benefits",
    "Important Differences",
]

_COMPARISON_SYSTEM_PROMPT = f"""You are comparing two versions of an organizational document. \
Respond ONLY with a valid JSON object - no markdown code fences, no commentary before or after - \
matching exactly this shape:

{{
  "overview": "one or two sentence summary of the overall comparison",
  "categories": [
    {{"category": "Policy Changes", "differences": ["..."]}},
    {{"category": "Dates", "differences": ["..."]}},
    {{"category": "Responsibilities", "differences": ["..."]}},
    {{"category": "Eligibility", "differences": ["..."]}},
    {{"category": "Benefits", "differences": ["..."]}},
    {{"category": "Important Differences", "differences": ["..."]}}
  ],
  "additions": ["content present in Document B but not Document A"],
  "removals": ["content present in Document A but not Document B"]
}}

Include every category listed above even if its "differences" list is empty. Base your answer \
only on the two documents provided - never invent information. If a category has no relevant \
differences, leave its list empty rather than fabricating content."""


@dataclass
class ComparisonResult:
    document_a: Document
    document_b: Document
    overview: str
    categories: List[dict]
    additions: List[str]
    removals: List[str]
    used_summaries: bool


def _normalize_comparison(data: dict) -> dict:
    """
    Guarantees the output always has exactly COMPARISON_CATEGORIES (in
    order, backfilled empty if the LLM omitted one) and correctly-typed
    lists, regardless of what the LLM actually returned.
    """
    provided: dict = {}
    for item in data.get("categories") or []:
        if isinstance(item, dict) and "category" in item:
            differences = item.get("differences") or []
            if not isinstance(differences, list):
                differences = [str(differences)]
            provided[str(item["category"])] = [str(d) for d in differences]

    categories = [
        {"category": name, "differences": provided.get(name, [])} for name in COMPARISON_CATEGORIES
    ]

    def _as_str_list(value) -> List[str]:
        if not value:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(v) for v in value]

    return {
        "overview": str(data.get("overview") or ""),
        "categories": categories,
        "additions": _as_str_list(data.get("additions")),
        "removals": _as_str_list(data.get("removals")),
    }


def _parse_comparison_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Top-level JSON value was not an object.")
    except (json.JSONDecodeError, ValueError):
        # Graceful degradation: surface the raw response under "Important
        # Differences" rather than failing the whole comparison outright.
        return _normalize_comparison(
            {
                "overview": (
                    "The comparison could not be parsed into structured categories; "
                    "see Important Differences below for the raw response."
                ),
                "categories": [{"category": "Important Differences", "differences": [raw.strip()]}],
            }
        )

    return _normalize_comparison(data)


async def compare_documents(
    session: AsyncSession,
    actor,
    document_id_a,
    document_id_b,
    *,
    llm_provider: Optional[LLMProvider] = None,
) -> ComparisonResult:
    if document_id_a == document_id_b:
        raise InvalidOperationError("Cannot compare a document with itself.")

    document_a = await document_service.get_document(session, actor, document_id_a)
    document_b = await document_service.get_document(session, actor, document_id_b)

    for document in (document_a, document_b):
        if document.processing_status != ProcessingStatus.COMPLETED:
            raise InvalidOperationError(
                f"Document '{document.original_filename}' has not finished processing yet."
            )

    chunks_a = await document_chunk_repository.list_for_document_ordered(session, document_a.id)
    chunks_b = await document_chunk_repository.list_for_document_ordered(session, document_b.id)
    if not chunks_a or not chunks_b:
        raise InvalidOperationError("Both documents must have extracted content to compare.")

    provider = llm_provider or get_llm_provider()

    text_a = "\n\n".join(chunk.chunk_text for chunk in chunks_a)
    text_b = "\n\n".join(chunk.chunk_text for chunk in chunks_b)
    used_summaries = False

    if len(text_a) + len(text_b) > settings.max_context_length:
        text_a, _ = await summarization_service.summarize_chunks(provider, chunks_a, SummaryType.DETAILED)
        text_b, _ = await summarization_service.summarize_chunks(provider, chunks_b, SummaryType.DETAILED)
        used_summaries = True

    user_content = (
        f"Document A ({document_a.original_filename}):\n\n{text_a}\n\n---\n\n"
        f"Document B ({document_b.original_filename}):\n\n{text_b}"
    )
    messages = [
        {"role": "system", "content": _COMPARISON_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw_response = await provider.generate(messages)
    parsed = _parse_comparison_response(raw_response)

    return ComparisonResult(
        document_a=document_a,
        document_b=document_b,
        overview=parsed["overview"],
        categories=parsed["categories"],
        additions=parsed["additions"],
        removals=parsed["removals"],
        used_summaries=used_summaries,
    )
