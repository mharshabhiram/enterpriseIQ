"""Structure-aware chunking.

Paragraphs are packed into chunks of up to CHUNK_SIZE characters; long paragraphs
are split on sentence boundaries; each new chunk starts with the last
CHUNK_OVERLAP characters of the previous one (snapped to a word boundary).
Chunks never cross page boundaries, so every chunk has an exact page number,
and the nearest heading is kept as `section` for citations.
"""
import re
from dataclasses import dataclass

from app.ingestion.extractors import ExtractedPage

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
_NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*\.?|[IVX]+\.|Section\s+\d+|Article\s+\d+)\s+[A-Z][^.!?]{2,80}$")
_SENTENCES = re.compile(r"[^.!?]+[.!?]+[\"')\]]?\s*|[^.!?]+$")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    page: int | None
    section: str | None


def detect_heading(line: str) -> str | None:
    line = line.strip()
    if not line or len(line) > 120:
        return None
    md = _MD_HEADING.match(line)
    if md:
        return md.group(1).strip()
    if _NUMBERED_HEADING.match(line):
        return line
    # Short ALL-CAPS lines are usually headings in policy PDFs.
    if 3 <= len(line) <= 60 and line.isupper() and not line.endswith("."):
        return line.title()
    return None


def _split_units(paragraph: str, max_len: int) -> list[str]:
    """Split an over-long paragraph into sentence groups, hard-splitting giant sentences."""
    if len(paragraph) <= max_len:
        return [paragraph]
    units: list[str] = []
    for sentence in (s.strip() for s in _SENTENCES.findall(paragraph)):
        if not sentence:
            continue
        while len(sentence) > max_len:
            cut = sentence.rfind(" ", 0, max_len)
            cut = cut if cut > max_len // 2 else max_len
            units.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            units.append(sentence)
    return units


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def chunk_pages(pages: list[ExtractedPage], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    section: str | None = None

    for page in pages:
        if not page.text.strip():
            continue
        current = ""
        current_section = section
        has_new_content = False

        def flush() -> None:
            nonlocal current, has_new_content
            text = current.strip()
            if text and has_new_content:
                chunks.append(Chunk(index=len(chunks), text=text, page=page.page, section=current_section))
            current = _overlap_tail(text, chunk_overlap) if text else ""
            has_new_content = False

        for paragraph in (p.strip() for p in page.text.split("\n\n")):
            if not paragraph:
                continue
            lines = paragraph.split("\n")
            heading = detect_heading(lines[0])
            if heading:
                if has_new_content:
                    flush()
                current = ""  # don't carry overlap across a section change
                section = current_section = heading
                paragraph = "\n".join(lines[1:]).strip()
                if not paragraph:
                    continue
            for unit in _split_units(paragraph, chunk_size):
                if has_new_content and len(current) + len(unit) + 2 > chunk_size:
                    flush()
                current = f"{current}\n\n{unit}" if current else unit
                has_new_content = True
        flush()
    return chunks
