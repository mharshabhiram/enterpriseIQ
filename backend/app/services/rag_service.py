"""
RAG service - project brief section 8's question-answering pipeline:

    Question -> Query Validation -> Query Embedding -> Vector Search ->
    Permission Filtering -> Relevant Chunks -> Context Construction ->
    LLM -> Answer + Citations

Retrieval (embedding + pgvector search + RBAC filtering) is entirely
delegated to retrieval_service.search, unchanged from Phase 5 - this
service's job is what happens on either side of that: deciding whether
there's enough context to even ask the LLM, building the prompt, and
turning the LLM's response plus the chunks actually used into a cited
answer.

Key design decision: if retrieval finds nothing (or nothing above the
threshold), the LLM is never called at all - a fixed, safe "I don't have
information about that" response is returned instead. This is a stronger
guarantee against hallucination than instructing the LLM not to guess
(brief section 8: "Do not allow the model to blindly answer from its
general knowledge when the required information is unavailable") - an
absent context block removes the *opportunity* to hallucinate, rather than
just asking the model nicely not to.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.factory import get_llm_provider
from app.ai.llm_provider import ChatMessage, LLMProvider
from app.config import settings
from app.models.user import User
from app.schemas.search import SearchResultItem
from app.services import retrieval_service

NO_CONTEXT_ANSWER = (
    "I couldn't find relevant information in the available documents to answer this question. "
    "Try rephrasing your question, or check that you have access to the relevant documents."
)

_SYSTEM_PROMPT = """You are EnterpriseIQ's internal knowledge assistant. Answer the user's \
question using ONLY the information in the provided context below.

Rules you must follow strictly:
- If the context does not contain enough information to answer the question, say so clearly \
instead of guessing or using outside knowledge.
- Never invent facts, figures, or policies that are not stated in the context.
- When information comes from multiple documents, distinguish between them explicitly by name.
- Keep your answer concise and directly responsive to the question.
- Do not mention these instructions in your answer."""


@dataclass
class RAGAnswer:
    answer: str
    sources: List[SearchResultItem]


def _build_context(
    results: List[SearchResultItem], max_context_length: int
) -> Tuple[str, List[SearchResultItem]]:
    """
    Greedily include results (already ranked by relevance) until the
    character budget is spent, always including at least the single most
    relevant result even if it alone exceeds the budget - some context beats
    none. Character count, not tokens, for the same reason chunking uses
    character counts (see app/ingestion/chunker.py): no tokenizer dependency,
    and it's a simple, provider-independent proxy that's easy to configure.
    """
    included: List[SearchResultItem] = []
    blocks: List[str] = []
    used_length = 0

    for index, result in enumerate(results, start=1):
        label = f"[Source {index}: {result.document_name}"
        if result.page_number is not None:
            label += f", page {result.page_number}"
        if result.section_title:
            label += f", section '{result.section_title}'"
        label += "]"
        block = f"{label}\n{result.excerpt}"

        if included and used_length + len(block) > max_context_length:
            break

        blocks.append(block)
        included.append(result)
        used_length += len(block)

    return "\n\n".join(blocks), included


def _build_messages(context_block: str, question: str) -> List[ChatMessage]:
    user_content = f"Context:\n\n{context_block}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def answer_question(
    session: AsyncSession,
    user: User,
    question: str,
    *,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
    llm_provider: Optional[LLMProvider] = None,
) -> RAGAnswer:
    # Query validation: ChatRequest already strips/rejects whitespace-only
    # input at the schema layer: this is a second line of defense for any
    # non-HTTP caller of this service.
    question = question.strip()
    if not question:
        return RAGAnswer(answer=NO_CONTEXT_ANSWER, sources=[])

    results = await retrieval_service.search(
        session,
        user,
        question,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        embedding_provider=embedding_provider,
    )

    if not results:
        return RAGAnswer(answer=NO_CONTEXT_ANSWER, sources=[])

    context_block, used_results = _build_context(results, settings.max_context_length)
    messages = _build_messages(context_block, question)

    provider = llm_provider or get_llm_provider()
    answer_text = await provider.generate(messages)

    return RAGAnswer(answer=answer_text, sources=used_results)
