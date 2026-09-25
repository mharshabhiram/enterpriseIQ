"""
Text extraction, one function per supported format, dispatched by
`extract_text`. Each returns a list of ExtractedSegment - PDFs segment by
page (real page numbers), DOCX/Markdown segment by heading (section
titles), and plain text is a single segment. Table extraction from DOCX and
OCR for scanned/image-only PDFs are both out of scope for this phase (see
README "Future improvements").
"""
import re
from typing import List

import docx
import pymupdf

from app.ingestion.types import ExtractedSegment

_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def extract_pdf(path: str) -> List[ExtractedSegment]:
    segments: List[ExtractedSegment] = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                segments.append(ExtractedSegment(text=text, page_number=page_index))
    return segments


def extract_docx(path: str) -> List[ExtractedSegment]:
    document = docx.Document(path)
    segments: List[ExtractedSegment] = []
    current_title: str | None = None
    current_lines: List[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            segments.append(ExtractedSegment(text=text, section_title=current_title))
        current_lines.clear()

    for paragraph in document.paragraphs:
        style_name = paragraph.style.name if paragraph.style else ""
        text = paragraph.text.strip()
        if style_name and style_name.lower().startswith("heading"):
            flush()
            current_title = text or current_title
            continue
        if text:
            current_lines.append(text)
    flush()
    return segments


def extract_plain_text(path: str) -> List[ExtractedSegment]:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    text = content.strip()
    return [ExtractedSegment(text=text)] if text else []


def extract_markdown(path: str) -> List[ExtractedSegment]:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read()

    matches = list(_MD_HEADER_RE.finditer(content))
    if not matches:
        text = content.strip()
        return [ExtractedSegment(text=text)] if text else []

    segments: List[ExtractedSegment] = []
    if matches[0].start() > 0:
        preamble = content[: matches[0].start()].strip()
        if preamble:
            segments.append(ExtractedSegment(text=preamble))

    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            segments.append(ExtractedSegment(text=body, section_title=title))
    return segments


_EXTRACTORS = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "txt": extract_plain_text,
    "md": extract_markdown,
}


def extract_text(path: str, file_type: str) -> List[ExtractedSegment]:
    normalized = file_type.lower().lstrip(".")
    extractor = _EXTRACTORS.get(normalized)
    if extractor is None:
        raise ValueError(f"Unsupported file type for extraction: {file_type!r}")
    return extractor(path)
