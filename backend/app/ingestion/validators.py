"""
Upload validation.

Two layers, both server-side (never trust the client's declared content
type): the file extension/size against configured limits, then a lightweight
check that the file's actual bytes look like what its extension claims -
catching a renamed .exe or truncated upload before it ever reaches the
extraction step.
"""
import os
import zipfile

from app.config import settings
from app.utils.errors import FileTooLargeError, FileValidationError, UnsupportedFileTypeError


def validate_extension(original_filename: str) -> str:
    """Return the normalized (lowercase, no dot) extension, or raise."""
    _, ext = os.path.splitext(original_filename)
    normalized = ext.lower().lstrip(".")
    if not normalized or normalized not in settings.allowed_file_types:
        allowed = ", ".join(settings.allowed_file_types)
        raise UnsupportedFileTypeError(
            f"File type '{ext or '(none)'}' is not supported. Allowed types: {allowed}."
        )
    return normalized


def validate_size(file_size: int) -> None:
    if file_size <= 0:
        raise FileValidationError("Uploaded file is empty.")
    if file_size > settings.max_file_size:
        max_mb = settings.max_file_size / (1024 * 1024)
        raise FileTooLargeError(f"File exceeds the maximum allowed size of {max_mb:.0f} MB.")


def validate_content(path: str, file_type: str) -> None:
    """
    Lightweight magic-byte / structure check that the saved file's content
    actually matches its claimed extension. Deliberately not a full
    antivirus/format validator - just enough to reject an obviously
    mislabeled or corrupt file before spending time on extraction.
    """
    if file_type == "pdf":
        with open(path, "rb") as handle:
            header = handle.read(5)
        if not header.startswith(b"%PDF-"):
            raise FileValidationError("File does not appear to be a valid PDF.")

    elif file_type == "docx":
        # A .docx is a zip archive containing a specific OOXML marker file.
        if not zipfile.is_zipfile(path):
            raise FileValidationError("File does not appear to be a valid DOCX (not a zip archive).")
        with zipfile.ZipFile(path) as archive:
            if "[Content_Types].xml" not in archive.namelist():
                raise FileValidationError("File does not appear to be a valid DOCX document.")

    elif file_type in ("txt", "md"):
        with open(path, "rb") as handle:
            sample = handle.read(4096)
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileValidationError(f"File is not valid UTF-8 text: {exc}") from exc
