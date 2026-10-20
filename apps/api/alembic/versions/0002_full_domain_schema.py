"""Add SNS, DM, Embedding, Snapshot, Impression, Notification, Setting, and Moderation tables.

Revision ID: 0002_full_domain_schema
Revises: 0001_initial
"""

from alembic import op

from app.database import Base
from app import models  # noqa: F401


revision = "0002_full_domain_schema"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_embeddings_hnsw "
        "ON repository_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_repository_embeddings_hnsw")
