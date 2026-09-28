"""usage_ledger.trace_id 补真外键 —— **一笔查不到出处的钱,在总额里和真的一样**

Revision ID: 001a4c860fd8
Create Date: 2026-09-28

## 为什么要这条外键

`trace_id` 之前**不是外键**,于是那一列可以填任何字符串,
而**没有任何一层会发现**。

一条账目的 `trace_id` 指向空处的后果不是「查询报错」——
它照样被计入总额,只有点进去看「这笔钱花在哪次调用上」时才查不到。
**钱是真的,而它的出处是假的。**

(和 `index_members.embedding_id` 指向一张不存在的表是同一个形状,
 那次也是补真外键解决的。)

> 能用约束表达的,不要用判据表达:
> 外键在**每次 INSERT** 上生效,判据只在有人调用时生效。

## 加之前量过

现有 96 行:`trace_id` 为空 0 行、指向不存在的 trace 0 行。
所以这条约束加上去不会拦住任何历史数据 —— **量过再加,不是试着加**。

⚠️ `trace_id` 仍然允许为空(外键对 NULL 放行)。允许为空是有意的:
以后可能有「不属于任何一次调用」的用量(比如按月的固定费用),
而**逼它编一个 trace 比让它为空糟** —— 编出来的那个 id 会指向空处,
正是这条外键要防的事。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001a4c860fd8'
down_revision: Union[str, Sequence[str], None] = 'b492bd798649'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key('fk_usage_ledger_traces', 'usage_ledger', 'traces', ['project_id', 'trace_id'], ['project_id', 'id'], ondelete='RESTRICT')


def downgrade() -> None:
    op.drop_constraint('fk_usage_ledger_traces', 'usage_ledger', type_='foreignkey')
