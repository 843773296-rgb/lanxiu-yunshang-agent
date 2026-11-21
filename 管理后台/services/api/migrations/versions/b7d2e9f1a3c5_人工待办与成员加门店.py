"""人工待办和成员各加一列门店(store_id)

2026-11-21,用户拍(经评测线会话转):聊天站的人工介入要按门店分开 —— 店长只看到、只处理本店的单子。
memberships 原来没有门店维度(11-20 做 Webhook 时也因此没法「按门店身份跑」),这次加:
· memberships.store_id:这个人属于哪个门店;空 = 不限门店(总部 / 管理员),看全部
· human_requests.store_id:这张待办归哪个门店;挂起时按 runtime/门店范围.取门店 定,空 = 定不出门店(只有不限门店的人看得到)
都是可空文本,老数据不动:老成员都是「不限门店」,老待办都是「定不出门店」—— 和加列之前的行为一样(谁都看得到 → 只有不限门店的人看得到,
而现在所有成员都还没登记门店,所以仍是谁都看得到;管理员给店长登记门店的那一刻才开始分)。

Revision ID: b7d2e9f1a3c5
Revises: a3c7e1b2d4f6
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7d2e9f1a3c5'
down_revision: Union[str, Sequence[str], None] = 'a3c7e1b2d4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memberships', sa.Column('store_id', sa.Text(), nullable=True))
    op.add_column('human_requests', sa.Column('store_id', sa.Text(), nullable=True))
    op.create_index('ix_human_requests_proj_store', 'human_requests', ['project_id', 'store_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_human_requests_proj_store', table_name='human_requests')
    op.drop_column('human_requests', 'store_id')
    op.drop_column('memberships', 'store_id')
