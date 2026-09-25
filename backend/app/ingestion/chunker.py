"""
Chunking.

Splits each ExtractedSegment's text into overlapping chunks of
(approximately) `chunk_size` characters, sliding forward by
`chunk_size - chunk_overlap` each time. Cuts are nudged backward to the
nearest whitespace within a small lookback window so words aren't split
mid-token, at the cost of chunks being slightly shorter than chunk_size
sometimes - a reasonable trade for cleaner embeddings later (Phase 5).

Chunk sizes are character counts, not tokens - this project doesn't pull in
a tokenizer dependency; character count is a simple, provider-independent
proxy that's easy to reason about and configure via CHUNK_SIZE/CHUNK_OVERLAP.
"""
from typing import List

from app.ingestion.types import ChunkData, ExtractedSegment

_WHITESPACE_LOOKBACK_FRACTION = 4  # look back at most chunk_size // this many chars for a space


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    pieces: List[str] = []
    step = chunk_size - chunk_overlap
    length = len(text)
    start = 0

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            lookback = max(20, chunk_size // _WHITESPACE_LOOKBACK_FRACTION)
            boundary = text.rfind(" ", max(start, end - lookback), end)
            if boundary > start:
                end = boundary

        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= length:
            break
        start += step

    return pieces


def chunk_segments(
    segments: List[ExtractedSegment], *, chunk_size: int, chunk_overlap: int
) -> List[ChunkData]:
    """Chunk every segment in order, assigning a single running chunk_index across all of them."""
    chunks: List[ChunkData] = []
    index = 0
    for segment in segments:
        for piece in _split_text(segment.text, chunk_size, chunk_overlap):
            chunks.append(
                ChunkData(
                    chunk_index=index,
                    chunk_text=piece,
                    page_number=segment.page_number,
                    section_title=segment.section_title,
                )
            )
            index += 1
    return chunks
