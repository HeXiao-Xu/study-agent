"""S2-8 文件解析进度与错误信息

Revision ID: 0005_s2_8
Revises: 0004_s2_7
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_s2_8"
down_revision = "0004_s2_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("parse_progress", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("files", sa.Column("error_msg", sa.Text(), nullable=True))
    op.add_column(
        "files", sa.Column("parse_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "files", sa.Column("parse_finished_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint("ck_files_parse_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_parse_status",
        "files",
        "parse_status IN ('pending', 'parsing', 'done', 'failed')",
    )
    op.create_check_constraint(
        "ck_files_parse_progress", "files", "parse_progress BETWEEN 0 AND 100"
    )


def downgrade() -> None:
    op.drop_constraint("ck_files_parse_progress", "files", type_="check")
    op.drop_constraint("ck_files_parse_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_parse_status", "files", "parse_status IN ('pending', 'done')"
    )
    op.drop_column("files", "parse_finished_at")
    op.drop_column("files", "parse_started_at")
    op.drop_column("files", "error_msg")
    op.drop_column("files", "parse_progress")