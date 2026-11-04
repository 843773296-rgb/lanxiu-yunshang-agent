"""意见提为样本_店长复核

DF-03 意见收集 PRD 第三阶段「证明改得有效」第一刀(2026-11-04):期望结果 → 待审核样本 → 店长复核。
用户拍:**总部运营提、店长复核**(两人点头才算)、**店长在聊天站里复核**。
只扩时间线的动作:提为样本 / 店长通过 / 店长退回(退回要写理由;通过可以不写)。
样本本身进现有的 samples 表(review_status 待复核 → 已通过 / 已退回),不另起一张。

Revision ID: 13fd23fe5b7f
Revises: cbd5353d91e6
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '13fd23fe5b7f'
down_revision: Union[str, Sequence[str], None] = 'cbd5353d91e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

旧动作 = "action_code in ('开始核实', '请求补充', '关联问题', '答复', '不采纳', '重开', '提的人补充')"
新动作 = ("action_code in ('开始核实', '请求补充', '关联问题', '答复', '不采纳', '重开', '提的人补充', "
          "'提为样本', '店长通过', '店长退回')")
旧说明 = "action_code in ('开始核实', '关联问题', '提的人补充') or note is not null"
新说明 = "action_code in ('开始核实', '关联问题', '提的人补充', '店长通过') or note is not null"


def upgrade() -> None:
    op.drop_constraint('ck_opinion_events_action', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_action', 'opinion_events', 新动作)
    op.drop_constraint('ck_opinion_events_note', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_note', 'opinion_events', 新说明)


def downgrade() -> None:
    import sqlalchemy as sa
    n = op.get_bind().execute(sa.text(
        "select count(*) from opinion_events where action_code in ('提为样本', '店长通过', '店长退回')")).scalar()
    if n:
        raise RuntimeError(f"opinion_events 里有 {n} 行样本复核的记录,旧结构装不下 —— 时间线只追加不删,不自动删;"
                           "要降级先导出这些行、确认可以丢再手动处理")
    op.drop_constraint('ck_opinion_events_note', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_note', 'opinion_events', 旧说明)
    op.drop_constraint('ck_opinion_events_action', 'opinion_events', type_='check')
    op.create_check_constraint('ck_opinion_events_action', 'opinion_events', 旧动作)
