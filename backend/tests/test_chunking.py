import io

from app.ingestion.chunking import chunk_pages, detect_heading
from app.ingestion.cleaning import clean_text
from app.ingestion.extractors import ExtractedPage, extract


def test_chunks_respect_size_and_keep_page_numbers():
    pages = [ExtractedPage(page=i, text=("Employees accrue leave monthly. " * 60)) for i in (1, 2)]
    chunks = chunk_pages(pages, chunk_size=500, chunk_overlap=80)
    assert len(chunks) > 4
    assert all(len(c.text) <= 500 + 80 for c in chunks)
    assert {c.page for c in chunks} == {1, 2}
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_overlap():
    pages = [ExtractedPage(page=1, text=" ".join(f"Sentence number {i} ends here." for i in range(200)))]
    chunks = chunk_pages(pages, chunk_size=400, chunk_overlap=100)
    assert chunks[0].text.split()[-1] in chunks[1].text


def test_markdown_headings_become_sections():
    text = "# Leave Policy\n\nEmployees get 25 days.\n\n## Remote Work\n\nTwo days per week from home."
    chunks = chunk_pages([ExtractedPage(page=None, text=text)], chunk_size=1000, chunk_overlap=100)
    assert [c.section for c in chunks] == ["Leave Policy", "Remote Work"]
    assert "Two days" in chunks[1].text and "25 days" not in chunks[1].text


def test_detect_heading_ignores_sentences():
    assert detect_heading("## Annual Leave") == "Annual Leave"
    assert detect_heading("This is a normal sentence that ends with a period.") is None


def test_clean_text_removes_control_chars_and_extra_whitespace():
    assert clean_text("a\x00b   c\n\n\n\nd") == "ab c\n\nd"


def test_empty_input_yields_no_chunks():
    assert chunk_pages([ExtractedPage(page=1, text="   ")], 500, 50) == []


def test_pdf_extraction_keeps_pages():
    import fitz

    pdf = fitz.open()
    for body in ("Page one talks about leave.", "Page two talks about security."):
        pdf.new_page().insert_text((72, 72), body)
    result = extract(pdf.tobytes(), "pdf")
    assert result.page_count == 2
    assert [p.page for p in result.pages] == [1, 2] and "security" in result.pages[1].text


def test_docx_headings_become_markdown_sections():
    import docx

    d = docx.Document()
    d.add_heading("Remote Work", level=1)
    d.add_paragraph("Staff may work from home two days per week.")
    buf = io.BytesIO()
    d.save(buf)
    text = extract(buf.getvalue(), "docx").pages[0].text
    assert text.startswith("# Remote Work")
    chunks = chunk_pages(extract(buf.getvalue(), "docx").pages, 1000, 100)
    assert chunks[0].section == "Remote Work"
