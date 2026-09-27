"""chunks 记下切它的解析器和切片器版本

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27

## 为什么加这两列

索引构建的输入指纹要含**切片器版本** —— 少了它,改过 chunker 的合并规则之后
续做会产出一半旧边界一半新边界的**混血索引**(检索照样跑,只是答得怪)。

而那个版本原本只能从**当前代码的常量**读(`chunker.切片器版本`),
这隐含一个假设:**库里的片段是用当前版本切的**。

那个假设现在成立(只有 seg-1),但它会在第一次改 chunker 时失效,**而且不报错**:
指纹算出 seg-2、续做判定说「输入变了,新建」,看起来完全正常 ——
实际那些旧片段仍然是 seg-1 切的,新建的构建会把它们当 seg-2 索引。

> **把「我假设 X」变成「库里记着 X」,代价是一个字段。**

记在行上之后,指纹从**片段实际记的版本**算,判据从「假设」变成「读数据」;
而且「混着切的片段」(一批 seg-1 一批 seg-2)能当场被发现。

## backfill:现有的 71 个片段确实是 md-1 / seg-1 切的

不是猜的 —— 它们是 2026-09-27 由 `tools/ingest_lanxiu.py` 一次导入的,
而那时 `parser.解析器版本 == "md-1"`、`chunker.切片器版本 == "seg-1"`。

⚠️ **只 backfill `created_by = 'ingest'` 的行。** 别的来源(以后会有接口上传)
不该被这次迁移代填一个版本号 —— **填错的版本号比空的更糟**:
空的会让「该新建还是续做」保守地选新建(见 `index_plan.py`),
填错的会让它放心地续做。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("chunker_version", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("parser_version", sa.Text(), nullable=True))
    # 只填导入脚本产生的那些 —— 见文件头最后一段。
    op.execute("""
        update chunks set chunker_version = 'seg-1', parser_version = 'md-1'
         where created_by = 'ingest'
           and chunker_version is null and parser_version is null
    """)


def downgrade() -> None:
    op.drop_column("chunks", "parser_version")
    op.drop_column("chunks", "chunker_version")
