"""embedding 维度 1536 → 512(接真模型 BGE-small-zh-v1.5)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-27

## 为什么改

首版按 1536 建(OpenAI text-embedding-3-small 的维度),那时只有 mock 向量。
用户 2026-09-27 拍了**本地模型**:BGE-small-zh-v1.5 + onnxruntime ——
不花钱、离线跑、**知识库内容不出这台机器**(业务拍板记录里有
「我摆过的代价,业务知情后仍然这么选」这类内部口径)。

它的 `hidden_size` 是 **512**(读 `config.json`,不是猜的)。

理由是用户问过「DeepSeek 能做 embedding 不」之后查出来的事实:
**Anthropic 和 DeepSeek 都不提供 embedding API**
(实测 DeepSeek 的 `/models` 只有两个文本生成模型,`/embeddings` 返回 404)。
所以真向量只有两条路:本地模型或付费 API。

## 这次迁移正是那个设计决定的**代价兑现**

`embeddings.embedding` 的维度写死在列类型上(`vector(N)`),不是用无维度的
`vector`。当时的理由和代价都写在 `contract/entities.py` 里:

  · **会报错的代价**:插错维度当场被 PostgreSQL 拒
    (实测 `expected 1536 dimensions, not 3`)
  · 对面那个方案(无维度 `vector`)**允许 3 维和 4 维躺在同一张表里**(实测,
    一声不响),而混维度的索引算出来的距离没有意义;而且它建不了 hnsw 索引

**今天就兑现了一次。下次换模型还要这么来一次,那是有意的。**

## 为什么可以直接改类型而不迁移数据

`embeddings` 表现在是空的(0 行)。之前那些是 **mock 向量** ——
从文本哈希派生的,语义无感知,没有保留价值。
而且每一行都带着 `是mock` 标记(它跟着数据走,不只写在文档里),
所以「哪些是假的」一直是明确的。

⚠️ 如果以后在有真数据时换模型,**不能这么改** ——
那时候要新建一列/新建一张表,把旧向量留着直到新索引建完并切换。
换模型意味着**全部重算**(输入指纹里有 `embedding模型id` 和 `embedding维度`,
所以系统会判定「输入变了,新建构建」而不是在混着两种向量的索引上续做)。
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 空表,直接改类型。⚠️ 非空时这一句会失败 —— **那是对的**:
    # 它逼着人去想「旧向量怎么办」,而不是让 1536 维的数据静默截断成 512。
    op.execute("alter table embeddings alter column embedding type vector(512)")


def downgrade() -> None:
    op.execute("alter table embeddings alter column embedding type vector(1536)")
