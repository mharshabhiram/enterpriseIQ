import uuid

import pytest

from app.config import Settings
from app.exceptions import UnsupportedFile
from app.security.jwt import create_access_token, decode_access_token
from app.security.passwords import hash_password, verify_password
from app.utils.files import absolute_path, detect_file_type, sanitize_filename, validate_content


def test_only_supported_extensions():
    assert detect_file_type("report.PDF") == "pdf"
    assert detect_file_type("notes.markdown") == "md"
    with pytest.raises(UnsupportedFile):
        detect_file_type("malware.exe")


def test_content_must_match_extension():
    with pytest.raises(UnsupportedFile):
        validate_content(b"MZ\x90\x00 not a pdf", "pdf")
    validate_content(b"%PDF-1.7 ...", "pdf")


def test_filename_sanitisation_blocks_traversal():
    name = sanitize_filename("../../etc/passwd.txt")
    assert "/" not in name and ".." not in name
    with pytest.raises(UnsupportedFile):
        absolute_path("../../etc/passwd")


def test_passwords_are_hashed_with_argon2():
    h = hash_password("S3cret-pass!")
    assert h.startswith("$argon2") and "S3cret" not in h
    assert verify_password("S3cret-pass!", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip_carries_role_and_version():
    uid = uuid.uuid4()
    token, _ = create_access_token(uid, "MANAGER", 3)
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid) and payload["role"] == "MANAGER" and payload["tv"] == 3


def test_overlap_must_be_smaller_than_half_chunk():
    with pytest.raises(ValueError):
        Settings(jwt_secret_key="x" * 32, chunk_size=400, chunk_overlap=300)
