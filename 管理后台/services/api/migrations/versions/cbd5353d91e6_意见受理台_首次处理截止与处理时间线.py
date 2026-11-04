"""意见受理台_首次处理截止与处理时间线

DF-03 意见受理台(2026-11-04;用户拍:总部运营统一受理 / 1 个工作日首次处理 / 工作日跳过周末和法定假日):
- opinions 加四列:首次处理截止(提交那一刻按 workdays.首次处理截止 算好存下)、截止依据(2026放假表 /
  只跳周末·放假表没覆盖)、首次处理时刻、给提的人看的答复
- 新表 opinion_events:每一次受理动作追加一行,不改不删(意见收集 PRD §7.1)

Revision ID: cbd5353d91e6
Revises: 2d2eb200f027
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cbd5353d91e6'
down_revision: Union[str, Sequence[str], None] = '2d2eb200f027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opinions', sa.Column('first_response_due_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('opinions', sa.Column('due_basis_code', sa.Text(), nullable=True))
    op.add_column('opinions', sa.Column('first_responded_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('opinions', sa.Column('reply_note', sa.Text(), nullable=True))
    op.create_table('opinion_events',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('opinion_id', sa.Text(), nullable=False),
    sa.Column('action_code', sa.Text(), nullable=False),
    sa.Column('from_status', sa.Text(), nullable=True),
    sa.Column('to_status', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_opinion_events_projects', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id', 'opinion_id'], ['opinions.project_id', 'opinions.id'], name='fk_opinion_events_opinions', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_opinion_events')
    )
    op.create_check_constraint('ck_opinion_events_action', 'opinion_events',
                               "action_code in ('开始核实', '请求补充', '关联问题', '答复', '不采纳', '重开', '提的人补充')")
    op.create_check_constraint('ck_opinion_events_note', 'opinion_events',
                               "action_code in ('开始核实', '关联问题', '提的人补充') or note is not null")


def downgrade() -> None:
    op.drop_table('opinion_events')
    op.drop_column('opinions', 'reply_note')
    op.drop_column('opinions', 'first_responded_at')
    op.drop_column('opinions', 'due_basis_code')
    op.drop_column('opinions', 'first_response_due_at')
