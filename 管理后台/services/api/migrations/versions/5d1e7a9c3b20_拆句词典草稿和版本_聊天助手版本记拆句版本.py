"""拆句词典草稿和版本 + 聊天助手版本记拆句版本(用户 2026-11-08 拍「拆分词典需要有配置的地方」→「新开拆句与路由页」+「大名单实时取,小的冻版本」)

split_dict_drafts 可改(PATCH 要 If-Match);split_dict_versions 不可变 —— 挂 版本行不可原地改() 触发器,一列都不放过
(参数给占位,原因见 07b867630470:不给参数时函数里遍历空数组直接报错,拦住了但拦的理由不对)。
chat_assistant_versions.split_version_id 可空:不选 = 不拆句,只按术语匹配(聊天站生产配置响应里给显式 null)。

Revision ID: 5d1e7a9c3b20
Revises: 0c3a95ae7655
Create Date: 2026-11-08 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5d1e7a9c3b20'
down_revision: Union[str, Sequence[str], None] = '0c3a95ae7655'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('split_dict_drafts',
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
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_split_dict_drafts_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_split_dict_drafts')
    )
    op.create_index('ix_split_dict_drafts_proj_updated', 'split_dict_drafts', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_table('split_dict_versions',
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
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_split_dict_versions_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_split_dict_versions'),
    sa.UniqueConstraint('project_id', 'key', 'content_hash', name='uq_split_dict_versions_project_id_key_content_hash'),
    sa.UniqueConstraint('project_id', 'key', 'version_no', name='uq_split_dict_versions_project_id_key_version_no')
    )
    op.create_index('ix_split_dict_versions_hash', 'split_dict_versions', ['content_hash'], unique=False)
    op.create_index('ix_split_dict_versions_proj_updated', 'split_dict_versions', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.execute("""create trigger trg_split_dict_versions_不可原地改 before update on split_dict_versions
                   for each row execute function 版本行不可原地改('_一列都不放过')""")
    op.add_column('chat_assistant_versions', sa.Column('split_version_id', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_assistant_versions', 'split_version_id')
    op.execute("drop trigger if exists trg_split_dict_versions_不可原地改 on split_dict_versions")
    op.drop_index('ix_split_dict_versions_proj_updated', table_name='split_dict_versions')
    op.drop_index('ix_split_dict_versions_hash', table_name='split_dict_versions')
    op.drop_table('split_dict_versions')
    op.drop_index('ix_split_dict_drafts_proj_updated', table_name='split_dict_drafts')
    op.drop_table('split_dict_drafts')
