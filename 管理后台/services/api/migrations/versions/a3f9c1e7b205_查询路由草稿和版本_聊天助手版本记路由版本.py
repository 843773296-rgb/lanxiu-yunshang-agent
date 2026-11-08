"""查询路由草稿和版本 + 聊天助手版本记路由版本(用户 2026-11-08 拍「查询理解」下实体识别 / 查询路由 / 意图识别各自列表-详情-配置、
各自冻版本、店长助手各选一版 —— 这是第二期)

route_drafts 可改(PATCH 要 If-Match);route_versions 不可变 —— 挂 版本行不可原地改() 触发器,一列都不放过。
chat_assistant_versions.route_version_id 可空:不选 = 全走默认路由(术语带定义、人名只占位、拿不准提示一句)。

Revision ID: a3f9c1e7b205
Revises: 8e2c4b6d1f37
Create Date: 2026-11-08 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a3f9c1e7b205'
down_revision: Union[str, Sequence[str], None] = '8e2c4b6d1f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('route_drafts',
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
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_route_drafts_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_route_drafts')
    )
    op.create_index('ix_route_drafts_proj_updated', 'route_drafts', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_table('route_versions',
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
    sa.ForeignKeyConstraint(['organization_id', 'project_id'], ['projects.organization_id', 'projects.id'], name='fk_route_versions_projects', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('project_id', 'id', name='pk_route_versions'),
    sa.UniqueConstraint('project_id', 'key', 'content_hash', name='uq_route_versions_project_id_key_content_hash'),
    sa.UniqueConstraint('project_id', 'key', 'version_no', name='uq_route_versions_project_id_key_version_no')
    )
    op.create_index('ix_route_versions_hash', 'route_versions', ['content_hash'], unique=False)
    op.create_index('ix_route_versions_proj_updated', 'route_versions', ['project_id', sa.literal_column('updated_at DESC')], unique=False)
    op.execute("""create trigger trg_route_versions_不可原地改 before update on route_versions
                   for each row execute function 版本行不可原地改('_一列都不放过')""")
    op.add_column('chat_assistant_versions', sa.Column('route_version_id', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_assistant_versions', 'route_version_id')
    op.execute("drop trigger if exists trg_route_versions_不可原地改 on route_versions")
    op.drop_index('ix_route_versions_proj_updated', table_name='route_versions')
    op.drop_index('ix_route_versions_hash', table_name='route_versions')
    op.drop_table('route_versions')
    op.drop_index('ix_route_drafts_proj_updated', table_name='route_drafts')
    op.drop_table('route_drafts')
