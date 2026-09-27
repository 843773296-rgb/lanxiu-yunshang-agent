"""index_builds 加 input_hash(输入指纹)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-27

规格 §19.3:「**输入版本变化则创建新构建,而不是复用错误结果**」。
没有这一列就判不出「输入变没变」—— 而「复用错误结果」的具体形状是:
续做一个输入已经变了的构建,得到一半旧边界一半新边界的**混血索引**。
它**不报错**,检索照样跑,只是答得怪。

⚠️ 允许为空,而且**空不等于「一样」**:
`knowledge/index_plan.py` 的 `该新建还是续做()` 遇到空指纹一律返回「新建」——
放它续做就等于在不知道输入有没有变的情况下续做,
而那正是这一列要防的事。老构建(这次迁移之前建的)因此会被强制重建,那是对的。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("index_builds", sa.Column("input_hash", sa.Text(), nullable=True))
    # 按 (知识库, 指纹) 找「这份输入有没有构建过」—— 续做判定的主查询走它
    op.create_index("ix_index_builds_proj_kb_input", "index_builds",
                    ["project_id", "knowledge_base_id", "input_hash"])


def downgrade() -> None:
    op.drop_index("ix_index_builds_proj_kb_input", table_name="index_builds")
    op.drop_column("index_builds", "input_hash")
