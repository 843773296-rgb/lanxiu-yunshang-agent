"""usage_ledger 补三列 —— **`source` 只是执行模式,不是供应商**

Revision ID: 60c49c3174eb
Create Date: 2026-09-28

## 起因:一个我自己犯的错

`source` 这一列当时有**两个含义**:

  · Worker 写的 100 行 → `execution_mode`(mock / live,是不是真跑的)
  · 精排写的 12 行     → **提供方**(anthropic)

两种值都是合法字符串,分组查询照样出结果,只是「mock」和「anthropic」
被并排列在同一列里,**看起来像两个供应商**。而它一声不响。

(这正是前一天修 `document_versions.object_key` 时写下的那句:
 「一列有两个含义而没人知道,比缺一列糟得多」—— 写完第二天自己跳进去了。
 **写在注释里对当下不起作用,起作用的是检查。**)

Worker 的含义在先,所以 `source` 归还给执行模式,缺的维度各给一列。

## 三列各自堵什么

    provider    谁提供的(anthropic / deepseek)。**成本必须按供应商算** ——
                并行会话实测 SDK 报的总价跨供应商差过 24 倍、135 倍
                (CLI 拿 Claude 的价目表去算 DeepSeek 的 token)
    caller      **谁花的**(门店助手 / 检索实验室)。没有它只答得出
                「一共花了多少」,答不出「门店助手今天花了多少」
    world_date  演示世界里的日期。门店助手跑在演示世界(停在某一天),
                而记录的时间戳是**真实时间** ——
                **两个时钟混在一张表里,而且不报错**

⚠️ `world_date` 是 **DATE 不是 TIMESTAMP**:它是日历日不是时刻。
存成 timestamp 会给它一个无意义的 00:00:00,而那个零点看起来像真的时刻 ——
**一个假装自己有精度的值,比一个粗一点的值危险。**

## 这次迁移**带数据修正**

那 12 行 `source='anthropic'` 要改回 `source='live'` + `provider='anthropic'`。
放在同一个迁移里是有意的:**结构和含义一起变**。
分两步做的话,中间那段时间里这一列仍然是两个含义,
而那段时间的任何一次查询都算错。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60c49c3174eb'
down_revision: Union[str, Sequence[str], None] = '001a4c860fd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('usage_ledger', sa.Column('provider', sa.Text(), nullable=True))
    op.add_column('usage_ledger', sa.Column('caller', sa.Text(), nullable=True))
    op.add_column('usage_ledger', sa.Column('world_date', sa.Date(), nullable=True))


    # ── 数据修正:把 source 里那 12 行「供应商」挪到 provider ──────────────
    # ⚠️ `where source not in ('mock','live')` 而不是 `where source='anthropic'`:
    # 写死 anthropic 的话,要是当时还混进过别的供应商名,那些就留在原地了 ——
    # **按「不是执行模式的都算错放」判,比按「等于某个已知错值」判宽,
    # 而这里要的正是宽**:我不知道还有没有别的。
    op.execute("""
        update usage_ledger
           set provider = source,
               source   = 'live'
         where source is not null and source not in ('mock', 'live')
    """)
    # mock 那些补上 provider:它们没有供应商(mock 适配器不经过任何供应商)。
    # **留 NULL,不填 'mock'** —— 填了之后 mock 会在「按供应商」的报表里
    # 冒充成一个供应商,而它一分钱都没花。
    op.execute("""
        update usage_ledger set caller = 'worker:prompt_run'
         where caller is null and resource = 'generate' and source = 'mock'
    """)
    op.execute("""
        update usage_ledger set caller = '检索实验室'
         where caller is null and resource = 'rerank'
    """)


def downgrade() -> None:
    op.drop_column('usage_ledger', 'world_date')
    op.drop_column('usage_ledger', 'caller')
    op.drop_column('usage_ledger', 'provider')
