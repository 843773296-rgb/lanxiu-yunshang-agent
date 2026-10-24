"""澜绣桥名单扩到六条流程要的能力

Revision ID: aa11d20fe090
Revises: 97e34436ff06
Create Date: 2026-10-24 20:14:37.845954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa11d20fe090'
down_revision: Union[str, Sequence[str], None] = '97e34436ff06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 名单只在 services/api/app/runtime/桥工具.py 一处;这里抄的是**这一版迁移那一刻**的名单 ——
# 迁移是历史记录,不能跟着名单文件变(否则重放老迁移得到的是新约束)。alembic 不比较 CHECK 的内容,
# 名单和库里的约束对不对得上由 tools/bridge_tools_check.py 盯着
_新 = ("取转写", "store_report", "list_reports", "call_opportunity", "get_customer", "customer_history",
      "get_stock", "get_order", "order_log", "get_workorder", "factory_chase", "delay_pending",
      "bad_ratings", "service_records", "get_aftersale", "get_maintain", "revive_list", "churn_watch",
      "stock_alert", "写跟进", "save_report", "confirm_report", "assign_task", "create_repair",
      "decide_repair", "close_bad_rating")
_旧 = ("取转写", "写跟进")


def _约束(名单):
    return "tool_name in (" + ", ".join(f"'{n}'" for n in 名单) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_bridge_calls_tool_name", "bridge_calls", type_="check")
    op.create_check_constraint("ck_bridge_calls_tool_name", "bridge_calls", _约束(_新))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_bridge_calls_tool_name", "bridge_calls", type_="check")
    op.create_check_constraint("ck_bridge_calls_tool_name", "bridge_calls", _约束(_旧))
