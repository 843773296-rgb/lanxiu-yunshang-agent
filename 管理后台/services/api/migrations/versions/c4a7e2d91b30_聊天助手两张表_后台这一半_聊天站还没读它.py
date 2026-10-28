"""聊天助手两张表_后台这一半_聊天站还没读它

用户 2026-10-28 拍「聊天助手配置页分两步」:第 1 步只做后台(看 / 改 / 出版本 / 审核上生产),
聊天站**还没读**这两张表 —— 聊天现在用的仍是代码里那一份。

Revision ID: c4a7e2d91b30
Revises: b3bd89331560
Create Date: 2026-10-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4a7e2d91b30'
down_revision: Union[str, Sequence[str], None] = 'b3bd89331560'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chat_assistants',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('role_key', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=True),
    sa.Column('definition', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('draft_revision', sa.BigInteger(), nullable=True),
    sa.Column('production_version_no', sa.Integer(), nullable=True),
    sa.Column('production_set_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('production_set_by', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.UniqueConstraint('project_id', 'role_key', name='uq_chat_assistants_project_id_role_key'),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_chat_assistants_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_chat_assistants'),
    )
    op.create_index('ix_chat_assistants_proj_updated', 'chat_assistants', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_index('ix_chat_assistants_proj_status', 'chat_assistants', ['project_id', 'status'], unique=False)
    op.create_table('chat_assistant_versions',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('organization_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revision', sa.BigInteger(), nullable=True),
    sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('chat_assistant_id', sa.Text(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('head_template', sa.Text(), nullable=False),
    sa.Column('foot_template', sa.Text(), nullable=True),
    sa.Column('tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model_name', sa.Text(), nullable=False),
    sa.Column('rule_pool_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rule_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('skill_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('prompt_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source_kind', sa.Text(), nullable=False),
    sa.Column('source_hash', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('change_note', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_chat_assistant_versions'),
    sa.UniqueConstraint('project_id', 'chat_assistant_id', 'version_no', name='uq_chat_assistant_versions_pi_cai_vn'),
    sa.ForeignKeyConstraint(['project_id', 'chat_assistant_id'], ['chat_assistants.project_id', 'chat_assistants.id'], name='fk_chat_assistant_versions_chat_assistants', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_chat_assistant_versions_projects', ondelete='RESTRICT'),
    )
    op.create_index('ix_chat_assistant_versions_hash', 'chat_assistant_versions', ['content_hash'], unique=False)
    op.create_index('ix_chat_assistant_versions_proj_updated', 'chat_assistant_versions', ['project_id', sa.literal_column('updated_at DESC')], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_assistant_versions_proj_updated', table_name='chat_assistant_versions')
    op.drop_index('ix_chat_assistant_versions_hash', table_name='chat_assistant_versions')
    op.drop_table('chat_assistant_versions')
    op.drop_index('ix_chat_assistants_proj_status', table_name='chat_assistants')
    op.drop_index('ix_chat_assistants_proj_updated', table_name='chat_assistants')
    op.drop_table('chat_assistants')
