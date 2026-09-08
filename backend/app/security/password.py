"""
Password hashing.

Uses the `bcrypt` library directly rather than passlib: passlib 1.7.4 (the
latest release) is incompatible with bcrypt>=4.1 - it crashes reading
`bcrypt.__about__.__version__` (removed upstream) and mishandles bcrypt's
72-byte input limit. This was confirmed while building this project, so we
avoid the extra dependency and call bcrypt directly instead.
"""
import bcrypt

_BCRYPT_MAX_BYTES = 72


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage in User.password_hash."""
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > _BCRYPT_MAX_BYTES:
        # Reject rather than silently truncate, so a long password isn't
        # ever partially checked - the caller should surface this as a
        # normal validation error.
        raise ValueError(f"Password must be at most {_BCRYPT_MAX_BYTES} bytes.")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored hash. Never raises on mismatch."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash, wrong encoding, etc. - treat as "does not match"
        # rather than letting an exception leak hash details to the caller.
        return False
