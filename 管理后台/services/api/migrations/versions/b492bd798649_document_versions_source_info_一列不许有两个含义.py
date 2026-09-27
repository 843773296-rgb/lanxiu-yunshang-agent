"""document_versions.source_info:**一列不许有两个含义**

Revision ID: b492bd798649
Revises: f6a7b8c9d0e1
Create Date: 2026-09-27

## 为什么要这一列

`object_key` 在契约里的含义是「对象存储的键」。实际上库里有两种:

  · `tools/ingest_lanxiu.py` 灌的那批 —— **仓库内相对路径**(首版没有对象存储)
  · 界面上传来的那批(M2)—— **对象存储键**

今天没有任何代码读这一列(正文在 `chunks` 里),所以矛盾是**潜伏的**。
它会咬第一个想读原文的人(「查看原文」按钮、重新切片),
而那时报出来的是「文件不存在」—— 根因却是这一列有两个含义。
**一列有两个含义而没人知道,比多一列糟得多。**

## ⚠️ 为什么在版本上而不在文档上

同一篇文档完全可以第一版是脚本灌的、第二版是界面传的。
放在 `documents` 上就等于假设一篇文档的所有版本来源相同 ——
而那个假设失效时**不报错**,只是读原文时读错一个文件。

## 老行怎么办

这一列对老行是 NULL。`knowledge/ingest.py` 的 `原文键()` 对 NULL **当场抛**,
**不退回「当相对路径试一次」**:猜对了没人知道,猜错了报出来的是
「文件不存在」。补老行用 `tools/backfill_object_keys.py`(默认 dry-run)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b492bd798649'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ⚠️ **nullable=True 是必须的**:这张表已经有行了,而 `source_info` 对它们
    # 没有正确的默认值 —— 填 `{"存储":"对象存储"}` 会**撒谎**(它们是仓库路径),
    # 填 `{"存储":"仓库相对路径"}` 是猜(以后再有别的来源就错了)。
    # **让它是 NULL,然后让读的那一侧当场抛** —— 「不知道」要能被表达出来。
    op.add_column('document_versions',
                  sa.Column('source_info', postgresql.JSONB(astext_type=sa.Text()),
                            nullable=True))


def downgrade() -> None:
    op.drop_column('document_versions', 'source_info')
