"""index_members 加唯一约束:同一个片段在一个构建里只出现一次

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-27

## 为什么必须有

`workers/worker.py` 开头就写着:「Outbox 的设计**保证**会有重复投递
(规格 §17.1:「重复投递是正常故障场景」)」。

而 `index_members` 原来只有 `(project_id, id)` 主键 ——
重复投递会造出**两条同 (build, chunk) 的成员行**。后果:
`knowledge/index_plan.py` 的 `算待做()` 把同一个片段算两次,
「陈旧成员」那条体检也会误报「指纹漏了一项」。

> **这不是防御性编程,是 Outbox 语义的必要配套。**

有了它,处理器的写入才能用 `on conflict (project_id, index_build_id, chunk_id)
do nothing` —— PostgreSQL 要求冲突目标**精确匹配**一个唯一约束。
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_index_members_project_id_index_build_id_chunk_id",
        "index_members", ["project_id", "index_build_id", "chunk_id"])


def downgrade() -> None:
    op.drop_constraint("uq_index_members_project_id_index_build_id_chunk_id",
                       "index_members", type_="unique")
