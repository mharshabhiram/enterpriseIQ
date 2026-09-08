"""
Shared enums for ORM models.

These map to native PostgreSQL ENUM types (created once, referenced by every
table that needs them). Keeping them here - rather than duplicating string
literals across models/schemas/services - is what makes it easy to add a new
role or status later (see project brief section 3: "additional roles can
easily be added later").
"""
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"


class ProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentVisibility(str, Enum):
    """
    PUBLIC documents are readable by any authenticated user with no need for
    a DocumentPermission row. RESTRICTED documents require an explicit grant
    (see GranteeType) - checked at query time, not just at the API layer.
    """

    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"


class GranteeType(str, Enum):
    """Whether a DocumentPermission row grants access to a role or a single user."""

    ROLE = "ROLE"
    USER = "USER"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
