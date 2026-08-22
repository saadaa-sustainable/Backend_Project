"""admin_context_documents -- uploaded md/pptx files the read-only AI
assistant can reference (app/api/routers/assistant.py). An operational
admin-panel table, not raw ingested data -- lives alongside
sync_batches/failed_jobs, not in scripts/sql/ with the Bronze DDL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-18

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_context_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_admin_context_documents_filename", "admin_context_documents", ["filename"])


def downgrade() -> None:
    op.drop_table("admin_context_documents")
