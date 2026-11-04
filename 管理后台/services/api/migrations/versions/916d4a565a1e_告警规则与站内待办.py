"""告警规则与站内待办

DF-04 第二步(2026-11-04;Dify 对标 §8.1 / C16)。用户拍判法:**连续 N 次越线才报、连续 M 次正常才恢复、样本不够那轮不算**。
alert_rules 带着自己的评估状态;alert_incidents 是站内待办(触发中 → 已恢复 / 已处理),eval_snapshot 能下钻到那一窗的运行。

Revision ID: 916d4a565a1e
Revises: 10533e81f21d
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '916d4a565a1e'
down_revision: Union[str, Sequence[str], None] = '10533e81f21d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_公共 = lambda: [
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
]
JB = lambda: postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table('alert_rules', *_公共(),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('filter_snapshot', JB(), nullable=False),
        sa.Column('metric_code', sa.Text(), nullable=False),
        sa.Column('direction_code', sa.Text(), nullable=False),
        sa.Column('threshold_value', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('window_minutes', sa.Integer(), nullable=False),
        sa.Column('min_sample_count', sa.Integer(), nullable=False),
        sa.Column('trigger_count', sa.Integer(), nullable=False),
        sa.Column('recover_count', sa.Integer(), nullable=False),
        sa.Column('dedupe_minutes', sa.Integer(), nullable=False),
        sa.Column('owner', sa.Text(), nullable=False),
        sa.Column('paused_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('breach_count', sa.Integer(), nullable=False),
        sa.Column('normal_count', sa.Integer(), nullable=False),
        sa.Column('firing_since_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_evaluated_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_notified_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_eval_snapshot', JB(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_alert_rules_projects', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('project_id', 'id', name='pk_alert_rules'))
    op.create_index('ix_alert_rules_proj_updated', 'alert_rules', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_table('alert_incidents', *_公共(),
        sa.Column('alert_rule_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('eval_snapshot', JB(), nullable=False),
        sa.Column('recovered_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('handled_by', sa.Text(), nullable=True),
        sa.Column('handled_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('reminded_count', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_alert_incidents_projects', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id', 'alert_rule_id'], ['alert_rules.project_id', 'alert_rules.id'], name='fk_alert_incidents_alert_rules', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('project_id', 'id', name='pk_alert_incidents'))
    op.create_index('ix_alert_incidents_proj_status', 'alert_incidents', ['project_id', 'status'], unique=False)
    op.create_index('ix_alert_incidents_proj_updated', 'alert_incidents', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    for t, 名, 式 in [
        ('alert_rules', 'ck_alert_rules_metric', "metric_code in ('终态成功率', '写入办成率', '失败次数', '端到端P95秒', '每个办成任务成本', '算不出金额笔数')"),
        ('alert_rules', 'ck_alert_rules_direction', "direction_code in ('低于', '高于')"),
        ('alert_rules', 'ck_alert_rules_window', "window_minutes between 5 and 10080"),
        ('alert_rules', 'ck_alert_rules_min_sample', "min_sample_count >= 1"),
        ('alert_rules', 'ck_alert_rules_counts', "trigger_count between 1 and 20 and recover_count between 1 and 20"),
        ('alert_rules', 'ck_alert_rules_dedupe', "dedupe_minutes between 5 and 10080"),
        ('alert_incidents', 'ck_alert_incidents_status', "status in ('触发中', '已恢复', '已处理')"),
        ('alert_incidents', 'ck_alert_incidents_handled', "status <> '已处理' or (handled_at is not null and note is not null)"),
    ]:
        op.create_check_constraint(名, t, 式)


def downgrade() -> None:
    op.drop_index('ix_alert_incidents_proj_updated', table_name='alert_incidents')
    op.drop_index('ix_alert_incidents_proj_status', table_name='alert_incidents')
    op.drop_table('alert_incidents')
    op.drop_index('ix_alert_rules_proj_updated', table_name='alert_rules')
    op.drop_table('alert_rules')
