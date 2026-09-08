"""
Importing this package registers every ORM model on `Base.metadata`, which
is required for Alembic autogenerate to see them (see alembic/env.py) and is
convenient for application code that just wants `from app.models import User`.
"""
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_permission import DocumentPermission
from app.models.message import Message
from app.models.message_source import MessageSource
from app.models.user import User

__all__ = [
    "User",
    "Document",
    "DocumentChunk",
    "DocumentPermission",
    "Conversation",
    "Message",
    "MessageSource",
    "AuditLog",
]
