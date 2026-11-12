"""问题单与问题处理时间线_意见关联问题

意见收集 PRD §4.2 / §5.2(2026-11-12):
- 新表 issues(问题单):标题 / 业务影响 / 复现 / 根因类别(9 类)/ 根因核实状态(分开一列)/ 方案 / 验收标准 /
  目标版本 / 依赖 / 负责人 / 处理时限(日期,可空 —— 几天算超时 PRD §10 待定)/ 完成证据 / 处理说明 /
  搁置理由 + 重新评估日期 / 指向主问题 / 状态 / 最近一次关闭时刻 / 重开次数
- 新表 issue_events(问题处理时间线):每一步追加一行,不改不删
- opinions 加 issue_id(同项目复合外键)+ CHECK「已关联问题 ⇔ 指着一张问题单」
- opinion_events 的动作加「重新归并」(已关联问题 → 核实中,要写为什么)

⚠️ 下面的 CHECK 字符串是**这一刻的快照**,来源是 services/api/app/issue_flow.py;那边改了要出新迁移
(`alembic check` 会报漂移提醒)。

Revision ID: f8fe8125142f
Revises: 59a1235c5e36
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f8fe8125142f'
down_revision: Union[str, Sequence[str], None] = '59a1235c5e36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

旧意见动作 = ("action_code in ('开始核实', '请求补充', '关联问题', '答复', '不采纳', '重开', '提的人补充', "
          "'提为样本', '店长通过', '店长退回')")
新意见动作 = ("action_code in ('开始核实', '请求补充', '关联问题', '答复', '不采纳', '重开', '提的人补充', "
          "'提为样本', '店长通过', '店长退回', '重新归并')")


def upgrade() -> None:
    # 「已关联问题」原来没有入口(接口没开),正常库里应该一条都没有;有的话新 CHECK 加不上 —— 先说清楚,不替人改
    n = op.get_bind().execute(sa.text("select count(*) from opinions where status = '已关联问题'")).scalar()
    if n:
        raise RuntimeError(f"opinions 里已经有 {n} 条「已关联问题」,可它们不知道关联的是哪张问题单 —— "
                           "新 CHECK「已关联问题 ⇔ issue_id 不空」加不上。先把这些行改回「核实中」(写进 opinion_events)再升级")
    op.create_table('issues',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('impact_note', sa.Text(), nullable=True),
    sa.Column('repro_note', sa.Text(), nullable=True),
    sa.Column('root_cause_type', sa.Text(), nullable=True),
    sa.Column('root_cause_status', sa.Text(), nullable=False),
    sa.Column('solution_note', sa.Text(), nullable=True),
    sa.Column('acceptance_note', sa.Text(), nullable=True),
    sa.Column('target_version', sa.Text(), nullable=True),
    sa.Column('dependency_note', sa.Text(), nullable=True),
    sa.Column('owner', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('completion_evidence_note', sa.Text(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('shelve_reason', sa.Text(), nullable=True),
    sa.Column('reevaluate_date', sa.Date(), nullable=True),
    sa.Column('duplicate_of_issue_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('last_closed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('reopen_count', sa.Integer(), nullable=False),
    sa.CheckConstraint("status in ('待分析', '已确认', '处理中', '待验证', '待发布', '观察中', '已验证关闭', '已搁置', '已重复')",
                       name='ck_issues_status'),
    sa.CheckConstraint("root_cause_type is null or root_cause_type in ('需求理解', '知识问题', '业务数据问题', 'Skill 问题', "
                       "'工具选择/执行问题', 'Workflow 问题', '模型生成问题', '权限或证据问题', '体验或流程问题')",
                       name='ck_issues_root_cause_type'),
    sa.CheckConstraint("root_cause_status in ('原因待核实', '原因已证实')", name='ck_issues_root_cause_status'),
    sa.CheckConstraint("root_cause_status <> '原因已证实' or root_cause_type is not null", name='ck_issues_proven_has_type'),
    sa.CheckConstraint("status <> '已搁置' or (shelve_reason is not null and reevaluate_date is not null)", name='ck_issues_shelved'),
    sa.CheckConstraint("(status = '已重复') = (duplicate_of_issue_id is not null)", name='ck_issues_duplicate'),
    sa.CheckConstraint("duplicate_of_issue_id is null or duplicate_of_issue_id <> id", name='ck_issues_not_self_duplicate'),
    sa.CheckConstraint("status <> '已验证关闭' or (resolution_note is not null and completion_evidence_note is not null)",
                       name='ck_issues_closed'),
    sa.CheckConstraint("reopen_count >= 0", name='ck_issues_reopen_count'),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_issues_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_issues')
    )
    op.create_index('ix_issues_proj_status', 'issues', ['project_id', 'status'], unique=False)
    op.create_index('ix_issues_proj_updated', 'issues', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_table('issue_events',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('issue_id', sa.Text(), nullable=False),
    sa.Column('action_code', sa.Text(), nullable=False),
    sa.Column('from_status', sa.Text(), nullable=True),
    sa.Column('to_status', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('change_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("action_code in ('新建', '改字段', '确认问题', '暂不处理', '标为重复', '开始处理', '提交验证', '验证通过', "
                       "'验证失败', '发布生效', '发布失败', '关闭', '观察期复发', '关闭后复发', '重新评估')",
                       name='ck_issue_events_action'),
    sa.CheckConstraint("action_code not in ('暂不处理', '标为重复', '验证失败', '发布失败', '观察期复发', '关闭后复发', '重新评估') "
                       "or note is not null", name='ck_issue_events_note'),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_issue_events_projects', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id', 'issue_id'], ['issues.project_id', 'issues.id'], name='fk_issue_events_issues', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_issue_events')
    )
    op.add_column('opinions', sa.Column('issue_id', sa.Text(), nullable=True))
    op.create_foreign_key('fk_opinions_issues', 'opinions', 'issues', ['project_id', 'issue_id'], ['project_id', 'id'],
                          ondelete='RESTRICT')
    op.create_check_constraint('ck_opinions_issue', 'opinions', "(status = '已关联问题') = (issue_id is not null)")
    op.drop_constraint('ck_opinion_events_action', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_action', 'opinion_events', 新意见动作)


def downgrade() -> None:
    # ⚠️ 有问题单 / 有关联 / 有「重新归并」记录就拒,**不替人删**(降级常是出事时的回滚路径,那时最不该自动删东西)
    b = op.get_bind()
    n单 = b.execute(sa.text("select count(*) from issues")).scalar()
    n归 = b.execute(sa.text("select count(*) from opinion_events where action_code = '重新归并'")).scalar()
    if n单 or n归:
        raise RuntimeError(f"库里有 {n单} 张问题单、{n归} 行「重新归并」记录,降到 59a1235c5e36 的结构装不下 —— "
                           "不自动删(那是处理记录)。要降级先导出这些行、确认可以丢再手动处理")
    op.drop_constraint('ck_opinion_events_action', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_action', 'opinion_events', 旧意见动作)
    op.drop_constraint('ck_opinions_issue', 'opinions', type_='check')
    op.drop_constraint('fk_opinions_issues', 'opinions', type_='foreignkey')
    op.drop_column('opinions', 'issue_id')
    op.drop_table('issue_events')
    op.drop_index('ix_issues_proj_updated', table_name='issues')
    op.drop_index('ix_issues_proj_status', table_name='issues')
    op.drop_table('issues')
