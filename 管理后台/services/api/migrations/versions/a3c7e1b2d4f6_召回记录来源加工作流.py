"""召回记录的来源多一个「工作流」

2026-11-20 夜,三期 3-5 知识检索节点做通:worker 的 _retrieve 每次检索照召回测试存一条 retrieval_runs(来源「工作流」),
而 ck_retrieval_runs_source 只认 '检索实验室' / 'chat' —— 第一次真跑就撞上 CheckViolation,记录没存上
(记一次试跑 不吞错,把原因带进了节点输出,所以看得见)。
10-08 建这张表时把来源写成枚举是有意的:「接新来源的那天要改这一行 + 出一个迁移,那正好是它真的接上了的落点」—— 今天就是那天。

Revision ID: a3c7e1b2d4f6
Revises: dd289ffffc98
Create Date: 2026-11-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a3c7e1b2d4f6'
down_revision: Union[str, Sequence[str], None] = 'dd289ffffc98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_retrieval_runs_source', 'retrieval_runs', type_='check')
    op.create_check_constraint('ck_retrieval_runs_source', 'retrieval_runs', "source in ('检索实验室', 'chat', '工作流')")


def downgrade() -> None:
    op.execute("delete from retrieval_runs where source = '工作流'")
    op.drop_constraint('ck_retrieval_runs_source', 'retrieval_runs', type_='check')
    op.create_check_constraint('ck_retrieval_runs_source', 'retrieval_runs', "source in ('检索实验室', 'chat')")
