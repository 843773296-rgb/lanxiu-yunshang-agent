"""日志采集策略自己的版本号,不再借项目 revision

2026-11-20,还体检欠账:日志采集策略(projects.retention_policy)原来拿 projects.revision 当乐观锁。
后果是两件不相干的事互相打架 —— 改项目别的设置让策略页 409,改策略又让项目设置页 409。
加一列 retention_policy_revision,老行补成 1(接口里也 coalesce 成 1,迁移前后读到的数一样)。

Revision ID: dd289ffffc98
Revises: b7c1d2e3f4a5
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dd289ffffc98'
down_revision: Union[str, Sequence[str], None] = 'b7c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('retention_policy_revision', sa.BigInteger(), nullable=True))
    op.execute("update projects set retention_policy_revision = 1 where retention_policy_revision is null")


def downgrade() -> None:
    op.drop_column('projects', 'retention_policy_revision')
