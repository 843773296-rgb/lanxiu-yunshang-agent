"""评测派发

DF-05(2026-11-05;Dify 对标 §8.2 / C17):新建一次评测要**真派出去执行** —— 每道题 × 候选 / 基线 × 两轮,
各派一次工作流运行(写入只演练);每次派了什么记在 evaluation_runs(执行回执),worker 每分钟收一次进度,
按 全部跑完 / 超时 / 超出费用上限 / 取消 落到终态。

evaluation_items 加 variant_code / round_no / execution_run_id:**老行回填「外部登记」/ 1**,两列从此不许空 ——
并行会话提醒:可空的话「迁移前的老数据」和「派发那一步漏写」会是同一个 NULL,数「每边每轮各几条」时合成一个看起来合理的数。

⚠️ **回填值「外部登记」和新行选的「外部登记」指的是同一件事,不用再加一个维度分开**(11-05 和并行会话对过):
迁移前的评测(共享库里 143 条)全是「建一条记录、等外面把结果登记进来」这一种做法 —— 当时只有这一条路,
登记逐题是唯一写入口。所以回填的和新选的,后面走的是同一条路(登记逐题、没有派发回执)。
判一对状态要不要分开,看的是**它们该触发的动作是不是相反**,不是来源是不是不同。
「该写而没写」由结构兜:三列 NOT NULL、CHECK 只收几个值、后台派发的评测拒收外部登记(409 EVALUATION_DISPATCHED)。

Revision ID: 5e1a0c7d2b94
Revises: 916d4a565a1e
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5e1a0c7d2b94'
down_revision: Union[str, Sequence[str], None] = '916d4a565a1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JB = lambda: postgresql.JSONB(astext_type=sa.Text())
TS = lambda: sa.TIMESTAMP(timezone=True)


def upgrade() -> None:
    for 名, 型 in [('executor_code', sa.Text()), ('timeout_minutes', sa.Integer()),
                   ('cost_cap_amount', sa.Numeric(precision=20, scale=6)), ('rounds_count', sa.Integer()),
                   ('dispatched_at', TS()), ('started_at', TS()), ('heartbeat_at', TS()),
                   ('deadline_at', TS()), ('ended_at', TS()), ('end_reason_code', sa.Text()),
                   ('end_detail', JB())]:
        op.add_column('evaluations', sa.Column(名, 型, nullable=True))
    # 老评测都是「建一条记录、等外面登记结果」那种
    op.execute("update evaluations set executor_code='外部登记' where executor_code is null")
    op.alter_column('evaluations', 'executor_code', nullable=False)

    op.add_column('evaluation_items', sa.Column('variant_code', sa.Text(), nullable=True))
    op.add_column('evaluation_items', sa.Column('round_no', sa.Integer(), nullable=True))
    op.add_column('evaluation_items', sa.Column('execution_run_id', sa.Text(), nullable=True))
    op.execute("update evaluation_items set variant_code='外部登记', round_no=1 where variant_code is null")
    op.alter_column('evaluation_items', 'variant_code', nullable=False)
    op.alter_column('evaluation_items', 'round_no', nullable=False)

    op.create_table('evaluation_runs',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('organization_id', sa.Text(), nullable=False),
        sa.Column('project_id', sa.Text(), nullable=False),
        sa.Column('created_at', TS(), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('updated_at', TS(), nullable=True),
        sa.Column('revision', sa.BigInteger(), nullable=True),
        sa.Column('archived_at', TS(), nullable=True),
        sa.Column('evaluation_id', sa.Text(), nullable=False),
        sa.Column('sample_id', sa.Text(), nullable=False),
        sa.Column('variant_code', sa.Text(), nullable=False),
        sa.Column('round_no', sa.Integer(), nullable=False),
        sa.Column('workflow_version_id', sa.Text(), nullable=False),
        sa.Column('execution_run_id', sa.Text(), nullable=False),
        sa.Column('job_id', sa.Text(), nullable=False),
        sa.Column('collected_at', TS(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_evaluation_runs_projects', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id', 'evaluation_id'], ['evaluations.project_id', 'evaluations.id'], name='fk_evaluation_runs_evaluations', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('project_id', 'id', name='pk_evaluation_runs'),
        sa.UniqueConstraint('project_id', 'evaluation_id', 'sample_id', 'variant_code', 'round_no', name='uq_evaluation_runs_pi_ei_si_vc_rn'))
    op.create_index('ix_evaluation_runs_proj_updated', 'evaluation_runs', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    for t, 名, 式 in [
        ('evaluations', 'ck_evaluations_executor', "executor_code in ('外部登记', '后台派发')"),
        ('evaluations', 'ck_evaluations_dispatch', "executor_code <> '后台派发' or (timeout_minutes between 1 and 1440 and cost_cap_amount > 0 and rounds_count between 1 and 5)"),
        ('evaluation_items', 'ck_evaluation_items_variant', "variant_code in ('外部登记', '候选', '基线')"),
        ('evaluation_items', 'ck_evaluation_items_round', "round_no between 1 and 5"),
        ('evaluation_runs', 'ck_evaluation_runs_variant', "variant_code in ('候选', '基线')"),
        ('evaluation_runs', 'ck_evaluation_runs_round', "round_no between 1 and 5"),
    ]:
        op.create_check_constraint(名, t, 式)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("select count(*) from evaluations where executor_code='后台派发'")).scalar()
    if n:
        raise RuntimeError(f"有 {n} 次「后台派发」的评测 —— 降级会丢掉它们的执行回执(evaluation_runs)和每边每轮的标记,"
                           f"剩下的逐题结果分不清是候选还是基线。先归档或导出再降级")
    op.drop_index('ix_evaluation_runs_proj_updated', table_name='evaluation_runs')
    op.drop_table('evaluation_runs')
    for t, 名 in [('evaluations', 'ck_evaluations_executor'), ('evaluations', 'ck_evaluations_dispatch'),
                  ('evaluation_items', 'ck_evaluation_items_variant'), ('evaluation_items', 'ck_evaluation_items_round')]:
        op.drop_constraint(名, t, type_='check')
    for 名 in ('variant_code', 'round_no', 'execution_run_id'):
        op.drop_column('evaluation_items', 名)
    for 名 in ('executor_code', 'timeout_minutes', 'cost_cap_amount', 'rounds_count', 'dispatched_at', 'started_at',
               'heartbeat_at', 'deadline_at', 'ended_at', 'end_reason_code', 'end_detail'):
        op.drop_column('evaluations', 名)
