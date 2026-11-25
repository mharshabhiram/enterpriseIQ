"""Seed development users (and optionally the sample documents).

    python -m app.seed            # users only
    python -m app.seed --samples  # users + sample_documents/*.md (embedded via Ollama)

Development credentials only — change or delete them before production.
"""
import argparse
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document, DocumentVisibility, Role, User
from app.security.passwords import hash_password
from app.services.document_service import DocumentService
from app.services.ingestion_service import process_document

DEV_PASSWORD = "EnterpriseIQ-Demo-2026!"
USERS = [
    ("Avery Admin", "admin@enterpriseiq.dev", "ADMIN", "IT & Security"),
    ("Morgan Manager", "manager@enterpriseiq.dev", "MANAGER", "Human Resources"),
    ("Eli Employee", "employee@enterpriseiq.dev", "EMPLOYEE", "Operations"),
]
SAMPLES = [
    ("hr-policy-2025.md", "HR Policy 2025", DocumentVisibility.PUBLIC, []),
    ("hr-policy-2026.md", "HR Policy 2026", DocumentVisibility.PUBLIC, []),
    ("it-security-standard.md", "IT Security Standard", DocumentVisibility.RESTRICTED, ["MANAGER"]),
]


def seed_users() -> dict[str, User]:
    out: dict[str, User] = {}
    with SessionLocal() as db:
        roles = {r.name: r.id for r in db.scalars(select(Role))}
        for name, email, role, dept in USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(name=name, email=email, password_hash=hash_password(DEV_PASSWORD), role_id=roles[role], department=dept)
                db.add(user)
                print(f"created {role:<8} {email}")
            out[role] = user
        db.commit()
    return out


def seed_samples(manager: User) -> None:
    candidates = [Path(__file__).resolve().parents[2] / "sample_documents", Path("/sample_documents")]
    folder = next((p for p in candidates if p.exists()), candidates[0])
    with SessionLocal() as db:
        manager = db.get(User, manager.id)
        for filename, title, visibility, roles in SAMPLES:
            if db.scalar(select(Document).where(Document.original_filename == filename)):
                continue
            path = folder / filename
            if not path.exists():
                print(f"skip {filename}: not found in {folder}")
                continue
            doc = DocumentService(db).upload(
                manager, filename=filename, data=path.read_bytes(), title=title, department="Human Resources",
                tags=["sample"], description=None, visibility=visibility, roles=roles, user_ids=[],
            )
            process_document(doc.id)
            status = db.get(Document, doc.id)
            db.refresh(status)
            print(f"{filename}: {status.processing_status.value} {status.processing_error or ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", action="store_true")
    args = parser.parse_args()
    users = seed_users()
    if args.samples:
        seed_samples(users["MANAGER"])
