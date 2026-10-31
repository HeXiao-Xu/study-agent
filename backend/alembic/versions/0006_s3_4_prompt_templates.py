"""S3-4 prompt_templates 表与 qa/v1 种子

Revision ID: 0006_s3_4
Revises: 0005_s2_8
Create Date: 2026-10-31
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_s3_4"
down_revision = "0005_s2_8"
branch_labels = None
depends_on = None

QA_V1_CONTENT = """你是该学生的私人学习助理。请严格按以下规则回答：
1. 只能依据【参考资料】回答；资料中没有的内容，明确说"你的资料里没有相关内容"。
2. 每个来自资料的结论后必须标注引用编号，如 [1][2]；编号必须对应参考资料。
3. 若你要补充资料之外的通用知识，必须另起一段并加前缀"【补充说明｜非你的资料】"。
4. 数学推导分步骤写，公式用 LaTeX（行内 $...$，独立 $$...$$）。
5. 不要编造页码、题号、数据。

【参考资料】
{{ context }}

【学生提问】{{ question }}
"""


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "variables_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("model_hint", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
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
            ["created_by"], ["users.id"], name="fk_prompt_templates_created_by"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        sa.UniqueConstraint(
            "name", "version", name="uq_prompt_templates_name_version"
        ),
    )
    op.create_index(
        "uq_prompt_templates_active_name",
        "prompt_templates",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_prompt_templates_name_created_at",
        "prompt_templates",
        ["name", "created_at"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO prompt_templates
                (name, version, content, variables_json, model_hint,
                 is_active, created_by, created_at, updated_at)
            VALUES
                (:name, :version, :content, CAST(:variables AS jsonb), NULL,
                 true, NULL, now(), now())
            """
        ).bindparams(
            name="qa",
            version="v1",
            content=QA_V1_CONTENT,
            variables=json.dumps(["context", "question"], ensure_ascii=False),
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_templates_name_created_at", table_name="prompt_templates"
    )
    op.drop_index(
        "uq_prompt_templates_active_name", table_name="prompt_templates"
    )
    op.drop_table("prompt_templates")