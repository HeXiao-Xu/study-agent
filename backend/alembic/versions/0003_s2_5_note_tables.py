"""S2-5 笔记相关表：files / notes / note_kps + note_chunks 外键

Revision ID: 0003_s2_5
Revises: 0002_s2_1
Create Date: 2026-10-26

警告：补外键前会删除“无主” note_chunks（user_id 不在 users 或 note_id 不在 notes）。
本库的 83 行是 S1-3 实验残留（user_id=1、users 为空），删除后不可恢复；
新建库上该语句是 no-op。保留它们就只能造占位用户/笔记，等于把脏数据带进正式库。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_s2_5"
down_revision = "0002_s2_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "parse_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("parse_result_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_files_user_id"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        sa.CheckConstraint(
            "parse_status IN ('pending', 'done')", name="ck_files_parse_status"
        ),
    )
    op.create_index("ix_files_user_id", "files", ["user_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("folder", sa.Text(), nullable=True),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notes_user_id"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_notes_subject_id"
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["files.id"], name="fk_notes_source_file_id"
        ),
    )
    op.create_index("ix_notes_user_id_subject_id", "notes", ["user_id", "subject_id"])
    op.create_index("ix_notes_tags_gin", "notes", ["tags"], postgresql_using="gin")

    op.create_table(
        "note_kps",
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], name="fk_note_kps_note_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"], ["knowledge_points.id"], name="fk_note_kps_kp_id"
        ),
        sa.PrimaryKeyConstraint("note_id", "kp_id"),
        sa.CheckConstraint("source IN ('ai', 'manual')", name="ck_note_kps_source"),
    )
    op.create_index("ix_note_kps_kp_id", "note_kps", ["kp_id"])

    # 补外键前清理无主行（条件删除：新库上无行可删）
    op.execute(
        sa.text(
            "DELETE FROM note_chunks "
            "WHERE user_id NOT IN (SELECT id FROM users) "
            "   OR note_id NOT IN (SELECT id FROM notes)"
        )
    )

    op.create_foreign_key(
        "fk_note_chunks_note_id_notes",
        "note_chunks",
        "notes",
        ["note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_note_chunks_user_id_users", "note_chunks", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_note_chunks_source_file_id_files",
        "note_chunks",
        "files",
        ["source_file_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_note_chunks_source_file_id_files", "note_chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_note_chunks_user_id_users", "note_chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_note_chunks_note_id_notes", "note_chunks", type_="foreignkey"
    )
    op.drop_index("ix_note_kps_kp_id", table_name="note_kps")
    op.drop_table("note_kps")
    op.drop_index("ix_notes_tags_gin", table_name="notes")
    op.drop_index("ix_notes_user_id_subject_id", table_name="notes")
    op.drop_table("notes")
    op.drop_index("ix_files_user_id", table_name="files")
    op.drop_table("files")