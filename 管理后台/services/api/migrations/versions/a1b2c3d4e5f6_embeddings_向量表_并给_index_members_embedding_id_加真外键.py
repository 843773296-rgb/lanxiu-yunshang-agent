"""embeddings 向量表,并给 index_members.embedding_id 加真外键

Revision ID: a1b2c3d4e5f6
Revises: bb336f6af9a9
Create Date: 2026-09-27

## 为什么有这次迁移

`index_members.embedding_id` 本来指向**一张不存在的表**。
它不是数据库外键,所以那一列可以填任何字符串,而没有任何一层会发现。

后果:「登记了向量」可以是纯粹的谎话 —— 索引构建照样报成功,
而那一段内容在检索里**永远不命中**。没有报错、没有告警。

应用层判据(`knowledge/index_plan.py` 的 `已经做完的()`)只能查「非空」。
**能用约束表达的不要用判据表达**:判据只在有人调用它时生效,
外键在每一次 INSERT 上生效,**包括我没想到的那些写入路径**。

## 三个设计决定,每个都是为了让坏法变成「会报错」

### ① 维度写死在列类型里(`vector(1536)`),不用无维度的 `vector`

量过:无维度的 `vector` 列**允许 3 维和 4 维躺在同一张表里**(试过,一声不响),
而且建不了 hnsw 索引(`column does not have dimensions`)。
规格 §18 要求「换了 Embedding 模型,旧向量不能混用」——
固定维度让**数据库直接执行**这一条:插错维度当场报错。

代价是换模型要一次迁移。那是个**会报错**的代价;
对面那个是「混维度静默存进去,检索时算出没有意义的距离」。

### ② 身份是 (文本, 模型),不是 (构建, 片段)

唯一键 `(project_id, text_hash, model_id)`。
同一段文本用同一个模型算出来的向量,**换了检索配置不需要重算** ——
检索配置改了要新建构建(§19.3),但那次新建可以把全部向量复用,
一次 Embedding 都不用重跑。绑构建就做不到这件事。

⚠️ 唯一键**不含 `dim`**:维度由模型决定。把它放进唯一键
等于承认「同一个模型可以产两种维度」,而那正是要防的事。

### ③ 和 chunks **没有**外键

关系是 `text_hash` 相等,而那不是一对一 ——
同一段文本会在多个片段里出现(重复的小标题、表格分隔行都踩过)。
指向某一个 chunk 就要在多个里挑一个,而挑哪个是随机的。

## 首版没有向量索引

没建 hnsw。几十个片段顺序扫够用(实测语料 4 份 381 行 → 30 来个片段)。
**上真量之前必须补** —— 这是欠账,不是设计。
补的时候要知道:hnsw 建索引要先定好 `vector_cosine_ops` 还是 `vector_l2_ops`,
而那取决于 Embedding 模型是不是归一化的 —— 换模型可能要重建索引。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'bb336f6af9a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector。**幂等**:本机已经装了 0.8.6,干净库(CI / 别人机器)要靠这一行。
    op.execute("create extension if not exists vector")

    op.create_table(
        "embeddings",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("text_hash", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("dim", sa.Integer(), nullable=True),
        # ⚠️ **`embedding` 那一列不在这儿声明** —— 见下面那句 ALTER。
        sa.PrimaryKeyConstraint("project_id", "id", name="pk_embeddings"),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"],
            name="fk_embeddings_projects", ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "text_hash", "model_id",
                            name="uq_embeddings_project_id_text_hash_model_id"),
    )
    # `embedding` 用一句 DDL 加上。**建表时不声明它**,因为 Alembic 的
    # `sa.Column` 里塞不进 `vector(1536)` 而不引入 pgvector 包 ——
    # 契约层故意不引它(CI 的 admin job 只装 sqlalchemy,多一个依赖就炸)。
    # 让数据库自己认这个类型,比在 Python 端翻译一层更少出错。
    op.execute("alter table embeddings add column embedding vector(1536)")

    op.create_index("ix_embeddings_proj_updated", "embeddings",
                    ["project_id", sa.text("updated_at DESC")])

    # **这就是这次迁移的重点。** 在这之前 embedding_id 指向一张不存在的表。
    op.create_foreign_key(
        "fk_index_members_embeddings", "index_members", "embeddings",
        ["project_id", "embedding_id"], ["project_id", "id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_index_members_embeddings", "index_members", type_="foreignkey")
    op.drop_index("ix_embeddings_proj_updated", table_name="embeddings")
    op.drop_table("embeddings")
    # ⚠️ **不 drop extension。** 别的东西可能也在用它,
    # 而回滚一次迁移不该拆掉整个数据库的能力。
