"""
On-disk file storage for uploaded documents.

Files are saved under settings.upload_dir using a generated (never
user-controlled) filename - see Document.filename vs original_filename in
the model. This keeps path traversal and filename-collision concerns out of
the picture entirely, since the stored name is always a fresh UUID.
"""
import os
import uuid

from fastapi import UploadFile

from app.config import settings
from app.utils.errors import FileTooLargeError

_READ_CHUNK_SIZE = 1024 * 1024  # 1 MB


def generate_stored_filename(extension: str) -> str:
    return f"{uuid.uuid4()}.{extension}"


def build_storage_path(stored_filename: str) -> str:
    return os.path.join(settings.upload_dir, stored_filename)


async def save_upload(file: UploadFile, stored_filename: str, *, max_size: int) -> int:
    """
    Stream the upload to disk in chunks (never load the whole file into
    memory), aborting - and cleaning up the partial file - the moment it
    exceeds `max_size`, rather than writing an arbitrarily large file to
    disk first and only checking afterwards.
    """
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = build_storage_path(stored_filename)
    size = 0
    try:
        with open(path, "wb") as out_file:
            while True:
                chunk = await file.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    max_mb = max_size / (1024 * 1024)
                    raise FileTooLargeError(f"File exceeds the maximum allowed size of {max_mb:.0f} MB.")
                out_file.write(chunk)
    except FileTooLargeError:
        delete_file(stored_filename)
        raise
    return size


def delete_file(stored_filename: str) -> None:
    """Best-effort delete - a missing file is not an error (e.g. already cleaned up)."""
    try:
        os.remove(build_storage_path(stored_filename))
    except FileNotFoundError:
        pass
