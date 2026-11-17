"""知识修订申请

执行手册 W28(2026-11-17;用户 11-12 拍「总部运营审,开发合并」,业务拍板 十八):
门店 / 顾问对 knowledge/*.md 里某一段口径提修订 → 总部运营审 → 采纳那一刻生成带括号注记的改动文本 → 开发照着改 md、过门禁 → 标已合并。
一张表 knowledge_revisions,状态 待审 / 已采纳 / 已驳回 / 已合并;审过的要有审的人和时刻、驳回要写说明、已合并要有合并时刻(库 CHECK 和 models.py 同一组)。

Revision ID: b7c1d2e3f4a5
Revises: 5a9f567d29b4
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = '5a9f567d29b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_revisions',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('knowledge_path', sa.Text(), nullable=False),
    sa.Column('section_name', sa.Text(), nullable=False),
    sa.Column('current_text', sa.Text(), nullable=False),
    sa.Column('proposed_text', sa.Text(), nullable=False),
    sa.Column('basis_note', sa.Text(), nullable=False),
    sa.Column('applicant_code', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('patch_text', sa.Text(), nullable=True),
    sa.Column('merged_by', sa.Text(), nullable=True),
    sa.Column('merged_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('待审', '已采纳', '已驳回', '已合并')", name='ck_knowledge_revisions_status'),
    sa.CheckConstraint("status = '待审' or (reviewed_by is not null and reviewed_at is not null)", name='ck_knowledge_revisions_reviewed'),
    sa.CheckConstraint("status <> '已驳回' or review_note is not null", name='ck_knowledge_revisions_rejected_note'),
    sa.CheckConstraint("status <> '已合并' or merged_at is not null", name='ck_knowledge_revisions_merged'),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'],
                            name='fk_knowledge_revisions_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_knowledge_revisions')
    )
    op.create_index('ix_knowledge_revisions_proj_status', 'knowledge_revisions', ['project_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_knowledge_revisions_proj_status', table_name='knowledge_revisions')
    op.drop_table('knowledge_revisions')
