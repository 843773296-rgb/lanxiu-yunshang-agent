"""调用链列表慢:spans / usage_ledger 按 (project_id, trace_id) 建索引,traces 按 (project_id, entry_kind, started_at desc)

2026-11-21(辅助目录《项目复审与优化清单 V2.0》P2-08 顺带的「运行记录列表接口慢」):GET /traces 空闲时就要 2.4 秒。
explain analyze:每一行数 spans 都是 Seq Scan(spans 只有主键 (project_id, id)),50 行 × 24ms;usage_ledger 走主键也是扫整个项目。
三条索引都是只读查询用的,不改数据;和 models.py 里新登记的 Index 同名。

Revision ID: c8e3f0a2b4d6
Revises: b7d2e9f1a3c5
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c8e3f0a2b4d6'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9f1a3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_spans_proj_trace', 'spans', ['project_id', 'trace_id'], unique=False)
    op.create_index('ix_usage_ledger_proj_trace', 'usage_ledger', ['project_id', 'trace_id'], unique=False)
    op.create_index('ix_traces_proj_kind_started', 'traces', ['project_id', 'entry_kind', sa.literal_column('started_at DESC')], unique=False)


def downgrade() -> None:
    op.drop_index('ix_traces_proj_kind_started', table_name='traces')
    op.drop_index('ix_usage_ledger_proj_trace', table_name='usage_ledger')
    op.drop_index('ix_spans_proj_trace', table_name='spans')
