"""S2-1 第一批业务表：users / user_relations / subjects / knowledge_points / knowledge_edges

Revision ID: 0002_s2_1
Revises: 0001_s1_3
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0002_s2_1"
down_revision = "0001_s1_3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("grade", sa.Text(), nullable=True),
        sa.Column(
            "role", sa.Text(), server_default=sa.text("'student'"), nullable=False
        ),
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
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(
            "role IN ('student', 'teacher', 'parent', 'admin')", name="ck_users_role"
        ),
    )

    op.create_table(
        "user_relations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["users.id"], name="fk_user_relations_teacher_id"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name="fk_user_relations_student_id"
        ),
        sa.UniqueConstraint(
            "teacher_id", "student_id", name="uq_user_relations_teacher_student"
        ),
        sa.CheckConstraint("teacher_id <> student_id", name="ck_user_relations_not_self"),
    )
    op.create_index("ix_user_relations_student_id", "user_relations", ["student_id"])

    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), server_default=sa.text("'高中'"), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.UniqueConstraint("code", name="uq_subjects_code"),
    )

    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("exam_weight", sa.Numeric(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("order_no", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_knowledge_points_subject_id"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["knowledge_points.id"],
            name="fk_knowledge_points_parent_id",
        ),
        sa.UniqueConstraint(
            "subject_id", "code", name="uq_knowledge_points_subject_code"
        ),
        sa.CheckConstraint("level >= 1 AND level <= 4", name="ck_knowledge_points_level"),
    )
    op.create_index("ix_knowledge_points_subject_id", "knowledge_points", ["subject_id"])
    op.create_index("ix_knowledge_points_parent_id", "knowledge_points", ["parent_id"])
    op.create_index(
        "ix_knowledge_points_embedding_hnsw",
        "knowledge_points",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("src_kp_id", sa.BigInteger(), nullable=False),
        sa.Column("dst_kp_id", sa.BigInteger(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["src_kp_id"], ["knowledge_points.id"], name="fk_knowledge_edges_src_kp_id"
        ),
        sa.ForeignKeyConstraint(
            ["dst_kp_id"], ["knowledge_points.id"], name="fk_knowledge_edges_dst_kp_id"
        ),
        sa.UniqueConstraint(
            "src_kp_id",
            "dst_kp_id",
            "relation",
            name="uq_knowledge_edges_src_dst_relation",
        ),
        sa.CheckConstraint(
            "relation IN ('prerequisite', 'related', 'confusable', 'contains')",
            name="ck_knowledge_edges_relation",
        ),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name="ck_knowledge_edges_source"
        ),
        sa.CheckConstraint("src_kp_id <> dst_kp_id", name="ck_knowledge_edges_not_self"),
    )
    op.create_index("ix_knowledge_edges_dst_kp_id", "knowledge_edges", ["dst_kp_id"])


def downgrade() -> None:
    op.drop_table("knowledge_edges")
    op.drop_table("knowledge_points")
    op.drop_table("subjects")
    op.drop_table("user_relations")
    op.drop_table("users")