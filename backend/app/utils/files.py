"""File validation and safe storage."""
import re
import unicodedata
import uuid
from pathlib import Path

from app.config import get_settings
from app.exceptions import FileTooLarge, UnsupportedFile

ALLOWED_EXTENSIONS = {"pdf": "pdf", "docx": "docx", "txt": "txt", "md": "md", "markdown": "md"}
# Magic bytes for binary formats; text formats are validated by decoding.
MAGIC = {"pdf": b"%PDF", "docx": b"PK\x03\x04"}


def detect_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFile("Unsupported file type. Upload PDF, DOCX, TXT or Markdown files.")
    return ALLOWED_EXTENSIONS[ext]


def sanitize_filename(filename: str) -> str:
    name = unicodedata.normalize("NFKD", Path(filename).name)
    stem, _, ext = name.rpartition(".")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem or name).strip("-.")[:80] or "document"
    stem = stem.replace("..", "-")
    ext = re.sub(r"[^a-z0-9]", "", ext.lower())
    return f"{stem}.{ext}" if ext else stem


def validate_content(data: bytes, file_type: str) -> None:
    settings = get_settings()
    if not data:
        raise UnsupportedFile("The file is empty.")
    if len(data) > settings.max_file_size:
        raise FileTooLarge(f"File is larger than {settings.max_file_size // (1024 * 1024)} MB.")
    magic = MAGIC.get(file_type)
    if magic and not data.startswith(magic):
        raise UnsupportedFile("The file content does not match its extension.")
    if file_type in {"txt", "md"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedFile("Text files must be UTF-8 encoded.") from exc


def store_file(data: bytes, safe_name: str) -> str:
    """Write under UPLOAD_DIR/<uuid>/<name>; returns the relative storage path."""
    root = Path(get_settings().upload_dir).resolve()
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    path = (folder / safe_name).resolve()
    if root not in path.parents:
        raise UnsupportedFile("Invalid file name.")
    path.write_bytes(data)
    return str(path.relative_to(root))


def absolute_path(storage_path: str) -> Path:
    root = Path(get_settings().upload_dir).resolve()
    path = (root / storage_path).resolve()
    if root not in path.parents:
        raise UnsupportedFile("Invalid storage path.")
    return path


def delete_file(storage_path: str) -> None:
    path = absolute_path(storage_path)
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass
