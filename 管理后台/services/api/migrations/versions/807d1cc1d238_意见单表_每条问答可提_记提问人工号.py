"""意见单表_每条问答可提_记提问人工号

DF-03 第 2 步(2026-11-04),口径照《意见收集与能力持续改进 PRD》(10-24)§3 / §5.1 / §7.1:
聊天站**每条问答**都能提「有帮助 / 有问题」,执行失败的那一轮也能报;独立建议不挂任何一轮。
记的是**提问的那个人**的澜绣工号(聊天站从登录会话换出来、只认这一轮的提问人),不是服务账号 U001。
挂在聊天站那一轮(chat_trace_ref)上;管理后台那条调用记录读的时候按 request_id 现对,不存一列会一直空着的 trace_id。
改之前那一版进 history_snapshot(PRD「修改反馈留版本」)。

Revision ID: 807d1cc1d238
Revises: 72a7e0a33c0e
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '807d1cc1d238'
down_revision: Union[str, Sequence[str], None] = '72a7e0a33c0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('opinions',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('chat_trace_ref', sa.Text(), nullable=True),
    sa.Column('session_ref', sa.Text(), nullable=True),
    sa.Column('verdict', sa.Text(), nullable=False),
    sa.Column('problem_type', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('expected_note', sa.Text(), nullable=True),
    sa.Column('impact_type', sa.Text(), nullable=True),
    sa.Column('asker_staff_code', sa.Text(), nullable=False),
    sa.Column('asker_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('history_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('promoted_sample_id', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_opinions_projects', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id', 'promoted_sample_id'], ['samples.project_id', 'samples.id'], name='fk_opinions_samples', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_opinions'),
    sa.UniqueConstraint('project_id', 'chat_trace_ref', 'asker_staff_code', name='uq_opinions_project_id_chat_trace_ref_asker_staff_code')
    )
    op.create_index('ix_opinions_proj_status', 'opinions', ['project_id', 'status'], unique=False)
    op.create_index('ix_opinions_proj_updated', 'opinions', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    # CHECK 约束 autogenerate 看不见(models._额外检查 里登记的),手写 —— 两边一个字不差
    for 名, 式 in [
        ('ck_opinions_source', "source in ('问答', '执行失败', '独立建议')"),
        ('ck_opinions_trace', "(source = '独立建议') = (chat_trace_ref is null)"),
        ('ck_opinions_verdict', "verdict in ('有帮助', '有问题')"),
        ('ck_opinions_failed', "source <> '执行失败' or verdict = '有问题'"),
        ('ck_opinions_problem', "(verdict = '有问题') = (problem_type is not null)"),
        ('ck_opinions_problem_note', "verdict = '有帮助' or note is not null"),
        ('ck_opinions_problem_type', "problem_type is null or problem_type in "
                                     "('答错', '没答全', '证据不支持', '查错对象', '太慢或失败', '不好操作', '新增能力', '其他')"),
        ('ck_opinions_impact', "impact_type is null or impact_type in ('仅影响本次', '反复出现', '影响业务办理')"),
        ('ck_opinions_status', "status in ('待受理', '待补充', '核实中', '已关联问题', '已答复', '不采纳', '已撤回')"),
    ]:
        op.create_check_constraint(名, 'opinions', 式)


def downgrade() -> None:
    op.drop_index('ix_opinions_proj_updated', table_name='opinions')
    op.drop_index('ix_opinions_proj_status', table_name='opinions')
    op.drop_table('opinions')
