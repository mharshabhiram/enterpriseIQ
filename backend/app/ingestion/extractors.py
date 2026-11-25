"""Text extraction per file type. Each extractor returns pages so chunks keep page numbers."""
import io
from dataclasses import dataclass

from app.exceptions import ProcessingError
from app.ingestion.cleaning import clean_text


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None
    text: str


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[ExtractedPage]
    page_count: int | None


def extract_pdf(data: bytes) -> ExtractionResult:
    import fitz  # PyMuPDF

    try:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ProcessingError("This PDF is password-protected.")
            pages = [ExtractedPage(i + 1, clean_text(page.get_text("text"))) for i, page in enumerate(pdf)]
            return ExtractionResult([p for p in pages if p.text], pdf.page_count)
    except ProcessingError:
        raise
    except Exception as exc:  # noqa: BLE001 — corrupted files raise many different errors
        raise ProcessingError("Could not read this PDF. It may be corrupted.") from exc


def extract_docx(data: bytes) -> ExtractionResult:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError("Could not read this DOCX file. It may be corrupted.") from exc
    parts: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "") or ""
        if style.lower().startswith("heading") or style.lower() == "title":
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            parts.append(f"{'#' * min(int(level), 6)} {text}")  # markdown heading → section metadata
        else:
            parts.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return ExtractionResult([ExtractedPage(None, clean_text("\n\n".join(parts)))], None)


def extract_text_file(data: bytes) -> ExtractionResult:
    return ExtractionResult([ExtractedPage(None, clean_text(data.decode("utf-8-sig", errors="replace")))], None)


EXTRACTORS = {"pdf": extract_pdf, "docx": extract_docx, "txt": extract_text_file, "md": extract_text_file}


def extract(data: bytes, file_type: str) -> ExtractionResult:
    extractor = EXTRACTORS.get(file_type)
    if extractor is None:
        raise ProcessingError(f"No extractor for file type '{file_type}'.")
    return extractor(data)
