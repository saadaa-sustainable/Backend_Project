"""initial schema: sync_batches, failed_jobs, raw_dump_meta

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- operational tables -------------------------------------------------
    op.create_table(
        "sync_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("account_key", sa.String(16), nullable=True),
        sa.Column("account_name", sa.String(128), nullable=True),
        sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_params", postgresql.JSONB, nullable=True),
        sa.Column("records_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.String(32), nullable=False, server_default="manual"),
    )
    op.create_index("ix_sync_batches_endpoint", "sync_batches", ["endpoint"])
    op.create_index("ix_sync_batches_status", "sync_batches", ["status"])
    op.create_index("ix_sync_batches_account_key", "sync_batches", ["account_key"])

    op.create_table(
        "failed_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("account_key", sa.String(16), nullable=True),
        sa.Column("account_name", sa.String(128), nullable=True),
        sa.Column("request_params", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_failed_jobs_batch_id", "failed_jobs", ["batch_id"])
    op.create_index("ix_failed_jobs_endpoint", "failed_jobs", ["endpoint"])
    op.create_index("ix_failed_jobs_resolved", "failed_jobs", ["resolved"])
    op.create_index("ix_failed_jobs_account_key", "failed_jobs", ["account_key"])

    # --- bronze: single consolidated raw dump table --------------------------
    op.create_table(
        "raw_dump_meta",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meta_id", sa.String(64), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("api_endpoint", sa.String(255), nullable=False),
        sa.Column("api_version", sa.String(16), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_params", postgresql.JSONB, nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(16), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("parent_ids", postgresql.JSONB, nullable=True),
        sa.Column("is_nested", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_raw_dump_meta_meta_id", "raw_dump_meta", ["meta_id"])
    op.create_index("ix_raw_dump_meta_batch_id", "raw_dump_meta", ["batch_id"])
    op.create_index("ix_raw_dump_meta_payload_hash", "raw_dump_meta", ["payload_hash"])
    op.create_index("ix_raw_dump_meta_processing_status", "raw_dump_meta", ["processing_status"])
    op.create_index("ix_raw_dump_meta_object_type", "raw_dump_meta", ["object_type"])
    op.create_index("ix_raw_dump_meta_batch_meta", "raw_dump_meta", ["batch_id", "meta_id"])
    op.create_index(
        "ix_raw_dump_meta_object_type_meta_id", "raw_dump_meta", ["object_type", "meta_id"]
    )
    op.create_index(
        "ix_raw_dump_meta_raw_payload_gin",
        "raw_dump_meta",
        ["raw_payload"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("raw_dump_meta")
    op.drop_table("failed_jobs")
    op.drop_table("sync_batches")
