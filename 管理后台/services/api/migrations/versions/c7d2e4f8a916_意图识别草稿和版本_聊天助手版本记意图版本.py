"""意图识别草稿和版本 + 聊天助手版本记意图版本(用户 2026-11-08 拍「查询理解」下三样各自冻版本、店长助手各选一版 —— 第三期)

intent_drafts 可改(PATCH 要 If-Match);intent_versions 不可变(触发器)。
chat_assistant_versions.intent_version_id 可空:不选 = 不做意图分类。只加不删,旧代码照常跑 —— 所以先单独落地、推送,再写用它的代码。

Revision ID: c7d2e4f8a916
Revises: a3f9c1e7b205
Create Date: 2026-11-09 11:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c7d2e4f8a916'
down_revision: Union[str, Sequence[str], None] = 'a3f9c1e7b205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('intent_drafts',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('key', sa.Text(), nullable=True),
    sa.Column('entries', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_intent_drafts_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_intent_drafts')
    )
    op.create_index('ix_intent_drafts_proj_updated', 'intent_drafts', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_table('intent_versions',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('entries', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_intent_versions_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_intent_versions'),
    sa.UniqueConstraint('project_id', 'key', 'content_hash', name='uq_intent_versions_project_id_key_content_hash'),
    sa.UniqueConstraint('project_id', 'key', 'version_no', name='uq_intent_versions_project_id_key_version_no')
    )
    op.create_index('ix_intent_versions_hash', 'intent_versions', ['content_hash'], unique=False)
    op.create_index('ix_intent_versions_proj_updated', 'intent_versions', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.execute("""create trigger trg_intent_versions_不可原地改 before update on intent_versions
                   for each row execute function 版本行不可原地改('_一列都不放过')""")
    op.add_column('chat_assistant_versions', sa.Column('intent_version_id', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_assistant_versions', 'intent_version_id')
    op.execute("drop trigger if exists trg_intent_versions_不可原地改 on intent_versions")
    op.drop_index('ix_intent_versions_proj_updated', table_name='intent_versions')
    op.drop_index('ix_intent_versions_hash', table_name='intent_versions')
    op.drop_table('intent_versions')
    op.drop_index('ix_intent_drafts_proj_updated', table_name='intent_drafts')
    op.drop_table('intent_drafts')
