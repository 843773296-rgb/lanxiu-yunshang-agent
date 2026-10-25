"""澜绣桥名单加库存补货和差评返修(补货预警 / 派补货跟进 / 差评研判 / 差评处置)

Revision ID: c94b50bd6a3e
Revises: 073afdf7e3da
Create Date: 2026-10-25 08:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c94b50bd6a3e'
down_revision: Union[str, Sequence[str], None] = '073afdf7e3da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 名单抄的是**这一版迁移那一刻**的(迁移是历史记录,不跟着名单文件变);对不对得上由 tools/bridge_tools_check.py 盯
_新 = ('取转写', 'store_report', 'list_reports', 'call_opportunity', 'get_customer', 'customer_history', 'get_stock', 'get_order', 'order_log', 'get_workorder', 'factory_chase', 'delay_pending', '订单交付风险', 'bad_ratings', 'service_records', 'get_aftersale', 'get_maintain', '差评研判', 'revive_list', 'churn_watch', '召回名单', 'stock_alert', '补货预警', '写跟进', 'save_report', 'confirm_report', 'assign_task', 'create_repair', 'decide_repair', 'close_bad_rating', '派回访任务', '派补货跟进', '差评处置')
_旧 = ('取转写', 'store_report', 'list_reports', 'call_opportunity', 'get_customer', 'customer_history', 'get_stock', 'get_order', 'order_log', 'get_workorder', 'factory_chase', 'delay_pending', '订单交付风险', 'bad_ratings', 'service_records', 'get_aftersale', 'get_maintain', 'revive_list', 'churn_watch', '召回名单', 'stock_alert', '写跟进', 'save_report', 'confirm_report', 'assign_task', 'create_repair', 'decide_repair', 'close_bad_rating', '派回访任务')


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
