"""Shared data structures passed between extraction and chunking."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExtractedSegment:
    """
    One unit of extracted text with whatever positional metadata the source
    format actually provides. For PDFs, one segment per page (page_number
    set, section_title None). For DOCX, one segment per section under a
    heading (section_title set, page_number None - DOCX has no fixed page
    concept until rendered). For TXT/MD, effectively one segment for the
    whole file (MD headings are treated as section boundaries, same as DOCX).
    """

    text: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None


@dataclass(frozen=True)
class ChunkData:
    """One chunk ready to become a DocumentChunk row (embedding filled in later, Phase 5)."""

    chunk_index: int
    chunk_text: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
