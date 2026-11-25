import uuid

from sqlalchemy.orm import Session

from app.exceptions import Forbidden, NotFound
from app.models import Document, DocumentPermission, DocumentStatus, DocumentVisibility, User
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.schemas.document import DocumentOut, PermissionsUpdate
from app.security.permissions import can_manage_document, can_upload
from app.services.audit_service import AuditAction, record
from app.utils.files import delete_file, detect_file_type, sanitize_filename, store_file, validate_content


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = DocumentRepository(db)

    def to_out(self, doc: Document, user: User) -> DocumentOut:
        out = DocumentOut.model_validate(doc)
        out.uploader_name = doc.uploader.name if doc.uploader else None
        out.can_manage = can_manage_document(user, doc)
        return out

    def upload(
        self,
        user: User,
        *,
        filename: str,
        data: bytes,
        title: str | None,
        department: str | None,
        tags: list[str],
        description: str | None,
        visibility: DocumentVisibility,
        roles: list[str],
        user_ids: list[uuid.UUID],
    ) -> Document:
        if not can_upload(user):
            record(self.db, AuditAction.PERMISSION_DENIED, user.id, "document", None, {"action": "upload"})
            raise Forbidden("Only managers and admins can upload documents.")
        file_type = detect_file_type(filename)
        validate_content(data, file_type)
        safe = sanitize_filename(filename)
        storage_path = store_file(data, safe)
        doc = Document(
            title=(title or filename.rsplit(".", 1)[0]).strip()[:255] or "Untitled",
            filename=safe,
            original_filename=filename[:255],
            file_type=file_type,
            file_size=len(data),
            storage_path=storage_path,
            uploaded_by=user.id,
            department=department or None,
            tags=[t.strip().lower()[:50] for t in tags if t.strip()][:10],
            description=description or None,
            visibility=visibility,
            processing_status=DocumentStatus.UPLOADED,
        )
        self.db.add(doc)
        self.db.flush()
        self._apply_grants(doc, roles, user_ids)
        record(self.db, AuditAction.DOCUMENT_UPLOADED, user.id, "document", doc.id, {"file_type": file_type}, commit=False)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def _apply_grants(self, doc: Document, roles: list[str], user_ids: list[uuid.UUID]) -> None:
        users = UserRepository(self.db)
        doc.permissions.clear()
        self.db.flush()
        if doc.visibility != DocumentVisibility.RESTRICTED:
            return
        for name in {r.strip().upper() for r in roles if r.strip()}:
            role = users.role(name)
            if role is None:
                raise NotFound(f"Unknown role '{name}'.", code="ROLE_NOT_FOUND")
            doc.permissions.append(DocumentPermission(role_id=role.id))
        for uid in set(user_ids):
            if users.get(uid) is None:
                raise NotFound("Unknown user in permissions.", code="USER_NOT_FOUND")
            doc.permissions.append(DocumentPermission(user_id=uid))

    def get_for_user(self, user: User, document_id: uuid.UUID) -> Document:
        doc = self.repo.get_accessible(user, document_id)
        if doc is None:
            # Same response whether it doesn't exist or isn't permitted: don't leak existence.
            raise NotFound("The requested document does not exist.", code="DOCUMENT_NOT_FOUND")
        return doc

    def get_manageable(self, user: User, document_id: uuid.UUID) -> Document:
        doc = self.get_for_user(user, document_id)
        if not can_manage_document(user, doc):
            record(self.db, AuditAction.PERMISSION_DENIED, user.id, "document", doc.id, {"action": "manage"})
            raise Forbidden("You can't manage this document.")
        return doc

    def delete(self, user: User, document_id: uuid.UUID) -> None:
        doc = self.get_manageable(user, document_id)
        storage_path = doc.storage_path
        record(self.db, AuditAction.DOCUMENT_DELETED, user.id, "document", doc.id, {"title": doc.title}, commit=False)
        self.db.delete(doc)
        self.db.commit()
        delete_file(storage_path)

    def update_permissions(self, user: User, document_id: uuid.UUID, data: PermissionsUpdate) -> Document:
        doc = self.get_manageable(user, document_id)
        doc.visibility = data.visibility
        self._apply_grants(doc, data.roles, data.user_ids)
        record(self.db, AuditAction.PERMISSION_CHANGED, user.id, "document", doc.id, data.model_dump(mode="json"), commit=False)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def mark_for_reprocessing(self, user: User, document_id: uuid.UUID) -> Document:
        doc = self.get_manageable(user, document_id)
        doc.processing_status = DocumentStatus.UPLOADED
        doc.processing_error = None
        self.db.commit()
        return doc
