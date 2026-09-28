"""application_drafts:候选配置和发布清单是两张表

`PATCH /applications/{id}/draft` 改的是**候选配置**,
`POST /applications/{id}/releases` 才把它**冻结**成一份发布清单。

## 为什么不共用 `release_manifests`

发布清单登记成 **不可变**:写下就不许改,靠 `content_hash` 认「同一份内容」。
而候选配置**天天在改** —— 把它们塞进同一张表,那张表就**同时是可变的和不可变的**,
而「这一行能不能改」要靠 `approval` 是不是空来推。
**一张表两个含义,这个仓库为这个形状付过三次代价了。**

## 为什么也不挂进 `graph_drafts`

那张表已经是「一行只挂 workflow 或 agent 之一」,而它自己的登记里写着
**「⚠️ 这条『二选一』数据库拦不住」**。再加第三种,是把一个已知的弱点变成更弱。

⚠️ revision id 用 `uuid.uuid4().hex[:12]` 生成,别手编。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "04960cbd2d9f"
down_revision = "5f53c80d57f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application_drafts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.BigInteger()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("application_id", sa.Text(), nullable=False),
        # 候选里挑的每一项依赖。**键是确切版本的 id,不是「最新」**。
        sa.Column("definition", postgresql.JSONB()),
        sa.PrimaryKeyConstraint("project_id", "id", name="pk_application_drafts"),
        # 一个应用只有一份候选 —— 两份候选的话,「出发布」出的是哪一份?
        sa.UniqueConstraint("project_id", "application_id",
                            name="uq_application_drafts_project_id_application_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "application_id"],
            ["applications.project_id", "applications.id"],
            name="fk_application_drafts_application"),
    )


def downgrade():
    op.drop_table("application_drafts")
