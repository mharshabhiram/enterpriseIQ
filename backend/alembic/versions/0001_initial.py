"""Initial schema: roles, users, documents, permissions, chunks (pgvector), conversations, audit logs.

Revision ID: 0001_initial
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.config import get_settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DIM = get_settings().embedding_dimensions


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.String(255)),
    )
    op.bulk_insert(
        roles,
        [
            {"id": 1, "name": "ADMIN", "description": "Full access: users, roles, all documents, audit logs"},
            {"id": 2, "name": "MANAGER", "description": "Upload and manage own documents, read permitted documents"},
            {"id": 3, "name": "EMPLOYEE", "description": "Search and chat over permitted documents"},
        ],
    )
    op.execute("SELECT setval('roles_id_seq', 3)")

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("token_version", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role_id", "users", ["role_id"])

    document_status = pg.ENUM("UPLOADED", "PROCESSING", "COMPLETED", "FAILED", name="document_status")
    document_visibility = pg.ENUM("PUBLIC", "RESTRICTED", name="document_visibility")
    op.create_table(
        "documents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("tags", pg.ARRAY(sa.String(50)), nullable=False, server_default="{}"),
        sa.Column("description", sa.Text),
        sa.Column("processing_status", document_status, nullable=False, server_default="UPLOADED"),
        sa.Column("processing_error", sa.Text),
        sa.Column("page_count", sa.Integer),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("visibility", document_visibility, nullable=False, server_default="PUBLIC"),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("embedding_dimensions", sa.Integer),
        *_ts(),
    )
    for col in ("file_type", "uploaded_by", "department", "processing_status"):
        op.create_index(f"ix_documents_{col}", "documents", [col])
    op.create_index("ix_documents_tags", "documents", ["tags"], postgresql_using="gin")

    op.create_table(
        "document_permissions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id", ondelete="CASCADE")),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.CheckConstraint("(role_id IS NULL) <> (user_id IS NULL)", name="ck_permission_single_target"),
        sa.UniqueConstraint("document_id", "role_id", name="uq_permission_doc_role"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_permission_doc_user"),
    )
    op.create_index("ix_document_permissions_document_id", "document_permissions", ["document_id"])
    op.create_index("ix_document_permissions_user_id", "document_permissions", ["user_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("page_number", sa.Integer),
        sa.Column("section", sa.String(255)),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "conversations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        *_ts(),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    message_role = pg.ENUM("user", "assistant", name="message_role")
    op.create_table(
        "messages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "message_sources",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", pg.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_number", sa.Integer, nullable=False),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("chunk_id", pg.UUID(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="SET NULL")),
        sa.Column("document_name", sa.String(255), nullable=False),
        sa.Column("page", sa.Integer),
        sa.Column("section", sa.String(255)),
        sa.Column("excerpt", sa.Text, nullable=False),
        sa.Column("relevance_score", sa.Float, nullable=False),
    )
    op.create_index("ix_message_sources_message_id", "message_sources", ["message_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("metadata", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    for table in ("audit_logs", "message_sources", "messages", "conversations", "document_chunks",
                  "document_permissions", "documents", "users", "roles"):
        op.drop_table(table)
    for enum in ("message_role", "document_visibility", "document_status"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
