"""意见单加独立建议_提交键防重

DF-03 第 2 步第二刀(2026-11-04,意见收集 PRD §3.1「与具体问答无关的建议从导航进入,允许没有 trace」/ §3.2 提交幂等键):
独立建议不挂任何一轮,评价记成「建议」;防重靠 submit_ref —— 挂一轮的那种靠 (项目, 那一轮, 工号) 唯一,
而独立建议的 chat_trace_ref 是空的,PG 把 NULL 当互不相同,那条唯一约束防不了它。

Revision ID: 2d2eb200f027
Revises: 807d1cc1d238
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2d2eb200f027'
down_revision: Union[str, Sequence[str], None] = '807d1cc1d238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opinions', sa.Column('submit_ref', sa.Text(), nullable=True))
    op.create_unique_constraint('uq_opinions_project_id_asker_staff_code_submit_ref', 'opinions',
                                ['project_id', 'asker_staff_code', 'submit_ref'])
    # CHECK 手写(models._额外检查 里那几条,一个字不差)
    op.drop_constraint('ck_opinions_verdict', 'opinions', type_='check')
    op.create_check_constraint('ck_opinions_verdict', 'opinions', "verdict in ('有帮助', '有问题', '建议')")
    op.drop_constraint('ck_opinions_problem', 'opinions', type_='check')
    op.create_check_constraint('ck_opinions_problem', 'opinions', "(verdict <> '有帮助') = (problem_type is not null)")
    op.create_check_constraint('ck_opinions_suggest', 'opinions', "(source = '独立建议') = (verdict = '建议')")
    op.create_check_constraint('ck_opinions_submit_ref', 'opinions', "source <> '独立建议' or submit_ref is not null")


def downgrade() -> None:
    # ⚠️ 旧结构装不下独立建议(没有「建议」这个评价、没有提交键)。**有就拒,不替人删** ——
    # 2026-11-04 带数据连跑迁移时撞到:不拦的话报的是「ck_opinions_problem 被某行违反」,看不出该怎么办
    n = op.get_bind().execute(sa.text("select count(*) from opinions where source = '独立建议'")).scalar()
    if n:
        raise RuntimeError(f"opinions 里有 {n} 条独立建议,降到 807d1cc1d238 的结构装不下它们 —— "
                           "不自动删(那是用户提的意见)。要降级先导出这些行、确认可以丢再手动删掉")
    op.drop_constraint('ck_opinions_submit_ref', 'opinions', type_='check')
    op.drop_constraint('ck_opinions_suggest', 'opinions', type_='check')
    op.drop_constraint('ck_opinions_problem', 'opinions', type_='check')
    op.create_check_constraint('ck_opinions_problem', 'opinions', "(verdict = '有问题') = (problem_type is not null)")
    op.drop_constraint('ck_opinions_verdict', 'opinions', type_='check')
    op.create_check_constraint('ck_opinions_verdict', 'opinions', "verdict in ('有帮助', '有问题')")
    op.drop_constraint('uq_opinions_project_id_asker_staff_code_submit_ref', 'opinions', type_='unique')
    op.drop_column('opinions', 'submit_ref')
