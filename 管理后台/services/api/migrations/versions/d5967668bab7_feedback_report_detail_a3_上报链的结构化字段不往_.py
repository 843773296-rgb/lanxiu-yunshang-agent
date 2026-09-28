"""feedback.report_detail —— **A3 上报链的结构化字段不往 `note` 里塞**

Revision ID: d5967668bab7
Create Date: 2026-09-28

## 为什么不用 `note`

`note` 在 `fieldtypes.显式类型` 里被钉成 **TEXT**,而那是个有意的决定:
它是给人看的一句话。

把幂等键、外部 trace、世界日期塞进去的后果是**查不了** ——
`note->>'幂等键'` 当场报 `operator does not exist: text ->> unknown`。

而幂等键必须查得了:查不了就没法判「这条判读上报过没有」,
于是重复上报会**把采纳率的分母撑大** —— 一个被撑大的分母会让采纳率
看起来在下降,而真相是同一条判读被数了三遍。

⚠️ 这是同一族的第二次(前一次:把裸字符串塞进 JSONB 的 `spans.error`)。
共同点是**没查列的真实类型就用了它** —— 而这个仓库恰好有一套很强的
类型登记,同一天还因为加新列没登记类型当场拦过一次。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5967668bab7'
down_revision: Union[str, Sequence[str], None] = '60c49c3174eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('feedback', sa.Column('report_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('feedback', 'report_detail')
