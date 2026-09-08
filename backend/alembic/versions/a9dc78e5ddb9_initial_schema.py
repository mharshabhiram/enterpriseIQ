"""initial schema

Revision ID: a9dc78e5ddb9
Revises: 
Create Date: 2026-09-06 14:14:21.468038

Generated with `alembic revision --autogenerate` from the Phase 2 models,
then hand-adjusted (per project conventions) in three ways autogenerate
cannot do on its own:

1. Enables the `vector` extension before any table uses the vector type.
2. Adds an HNSW cosine-similarity index on document_chunks.embedding.
   NOTE: because this index is created via raw SQL (pgvector's `hnsw` access
   method isn't representable as a plain sa.Index), `alembic check` /
   `--autogenerate` will always report it as a spurious "removed index" -
   this is expected and safe to ignore; do not let autogenerate drop it.
3. Manages the 5 custom Postgres ENUM types explicitly (created once up
   front, dropped once at the end) instead of letting each column's
   sa.Enum(...) auto-create/drop its type - the default behavior caused
   "type already exists" errors for `user_role`, which is shared by both
   users.role and document_permissions.role.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = 'a9dc78e5ddb9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every custom Postgres ENUM type used below, defined once here and reused
# (with create_type=False) in each column that needs it.
user_role_enum = postgresql.ENUM(
    "ADMIN", "MANAGER", "EMPLOYEE", name="user_role", create_type=False
)
processing_status_enum = postgresql.ENUM(
    "UPLOADED", "PROCESSING", "COMPLETED", "FAILED", name="processing_status", create_type=False
)
document_visibility_enum = postgresql.ENUM(
    "PUBLIC", "RESTRICTED", name="document_visibility", create_type=False
)
grantee_type_enum = postgresql.ENUM("ROLE", "USER", name="grantee_type", create_type=False)
message_role_enum = postgresql.ENUM("user", "assistant", name="message_role", create_type=False)


def upgrade() -> None:
    # Must run before any table declares a `vector` column.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create each ENUM type exactly once, up front.
    bind = op.get_bind()
    user_role_enum.create(bind, checkfirst=True)
    processing_status_enum.create(bind, checkfirst=True)
    document_visibility_enum.create(bind, checkfirst=True)
    grantee_type_enum.create(bind, checkfirst=True)
    message_role_enum.create(bind, checkfirst=True)

    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', user_role_enum, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('resource', sa.String(length=255), nullable=True),
        sa.Column('event_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)

    op.create_table(
        'conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conversations_user_id'), 'conversations', ['user_id'], unique=False)

    op.create_table(
        'documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('original_filename', sa.String(length=512), nullable=False),
        sa.Column('file_type', sa.String(length=20), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        sa.Column('processing_status', processing_status_enum, nullable=False),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('visibility', document_visibility_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_documents_processing_status'), 'documents', ['processing_status'], unique=False)
    op.create_index(op.f('ix_documents_uploaded_by'), 'documents', ['uploaded_by'], unique=False)

    op.create_table(
        'document_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_title', sa.String(length=512), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1536), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    # HNSW index for approximate nearest-neighbor cosine similarity search.
    # Rows with a NULL embedding (not yet processed) are simply not indexed.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        'document_permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('grantee_type', grantee_type_enum, nullable=False),
        sa.Column('role', user_role_enum, nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(grantee_type = 'ROLE' AND role IS NOT NULL AND user_id IS NULL) OR "
            "(grantee_type = 'USER' AND user_id IS NOT NULL AND role IS NULL)",
            name='ck_document_permissions_grantee_consistency',
        ),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_permissions_document_role', 'document_permissions', ['document_id', 'role'], unique=False)
    op.create_index('ix_document_permissions_document_user', 'document_permissions', ['document_id', 'user_id'], unique=False)

    op.create_table(
        'messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('role', message_role_enum, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)

    op.create_table(
        'message_sources',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=False),
        sa.Column('chunk_id', sa.UUID(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['chunk_id'], ['document_chunks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_message_sources_chunk_id'), 'message_sources', ['chunk_id'], unique=False)
    op.create_index(op.f('ix_message_sources_message_id'), 'message_sources', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_message_sources_message_id'), table_name='message_sources')
    op.drop_index(op.f('ix_message_sources_chunk_id'), table_name='message_sources')
    op.drop_table('message_sources')

    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')

    op.drop_index('ix_document_permissions_document_user', table_name='document_permissions')
    op.drop_index('ix_document_permissions_document_role', table_name='document_permissions')
    op.drop_table('document_permissions')

    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_table('document_chunks')

    op.drop_index(op.f('ix_documents_uploaded_by'), table_name='documents')
    op.drop_index(op.f('ix_documents_processing_status'), table_name='documents')
    op.drop_table('documents')

    op.drop_index(op.f('ix_conversations_user_id'), table_name='conversations')
    op.drop_table('conversations')

    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

    # Drop each ENUM type exactly once, after every table referencing it is gone.
    bind = op.get_bind()
    message_role_enum.drop(bind, checkfirst=True)
    grantee_type_enum.drop(bind, checkfirst=True)
    document_visibility_enum.drop(bind, checkfirst=True)
    processing_status_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)

    # Extension is left in place - other schemas/objects may depend on it and
    # dropping it is rarely what you want in a real environment.
