"""uploads 表:**上传成功不等于内容可用**

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-27

## 为什么要这张表

规格 §17.1 登记了 `POST /uploads` 和 `POST /uploads/{id}/complete` 两条接口,
说明是:

> **服务端校验之后才算文件引用** —— 上传成功不等于内容可用。

而**实体表里没有 `uploads`**(和 `embeddings` 同一形状:接口登记了、实体没有)。
那句话需要一个**能记「校验没校验过」的地方** —— 不能只靠返回值:
返回值是一次性的,而「这个文件能不能用」以后**每次引用都要问**。

## 状态机里 `已上传` 不是终态,也不等于可用

    待上传 → 已上传 → 已校验 / 校验失败
                    ↘ 已放弃

把「上传成功」当「内容可用」的后果:引用一个坏文件时报「解析失败」,
而根因是它**从来没被校验过** —— **错误指向解析器,而根因在上传那一步**。

⚠️ **校验失败是终态,不回到「待上传」** —— 同一个坏文件重传还是坏的。
要传新文件就新建一条上传,**旧那条留着当证据**:
删掉之后用户只会再传一次同一个坏文件。

⚠️ **`已放弃`(要了地址但没传)和「传了但没过」必须分得开** ——
前者没花存储,后者占着一份坏数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("byte_count", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        # ⚠️ **服务端校验时算的**,不信客户端报的 ——
        # 客户端算的哈希证明不了服务端收到的是同一份字节。
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("verify_detail", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "id", name="pk_uploads"),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_uploads_projects", ondelete="RESTRICT"),
    )
    op.create_index("ix_uploads_proj_updated", "uploads",
                    ["project_id", sa.text("updated_at DESC")])
    op.create_index("ix_uploads_proj_status", "uploads", ["project_id", "status"])
    # 内容哈希:认出「这份文件传过没有」。⚠️ **不做唯一约束** ——
    # 同一份内容可以被合法地传两次(两个知识库各要一份),
    # 而「同一份内容只许存在一条上传记录」会把第二次正常上传拒掉。
    op.create_index("ix_uploads_hash", "uploads", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_uploads_hash", table_name="uploads")
    op.drop_index("ix_uploads_proj_status", table_name="uploads")
    op.drop_index("ix_uploads_proj_updated", table_name="uploads")
    op.drop_table("uploads")
