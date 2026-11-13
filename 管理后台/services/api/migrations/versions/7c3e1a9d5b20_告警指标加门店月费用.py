"""告警指标加门店月费用

用户 11-13 拍第三十八条「模型费用到上限 80% 店长和总部都推」:总部那头 = 管理后台告警。
ck_alert_rules_metric 多收一个「门店月费用」(值从聊天站门店用量账现取,不走监测页;见 alert_rules.外部指标们)。
规则不在这里种(CI 新库没有澜绣项目),worker 扫告警时给澜绣项目种一条。

⚠️ 下面的 CHECK 字符串是这一刻的快照,来源是 alert_rules.指标们 + 外部指标们;那边改了要出新迁移。

Revision ID: 7c3e1a9d5b20
Revises: f112450e5aa7
Create Date: 2026-11-13 22:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '7c3e1a9d5b20'
down_revision: Union[str, Sequence[str], None] = 'f112450e5aa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

旧 = "metric_code in ('终态成功率', '写入办成率', '失败次数', '端到端P95秒', '每个办成任务成本', '算不出金额笔数')"
新 = "metric_code in ('终态成功率', '写入办成率', '失败次数', '端到端P95秒', '每个办成任务成本', '算不出金额笔数', '门店月费用')"


def upgrade() -> None:
    op.drop_constraint('ck_alert_rules_metric', 'alert_rules', type_='check')
    op.create_check_constraint('ck_alert_rules_metric', 'alert_rules', 新)


def downgrade() -> None:
    op.execute("delete from alert_incidents where alert_rule_id in (select id from alert_rules where metric_code = '门店月费用')")
    op.execute("delete from alert_rules where metric_code = '门店月费用'")
    op.drop_constraint('ck_alert_rules_metric', 'alert_rules', type_='check')
    op.create_check_constraint('ck_alert_rules_metric', 'alert_rules', 旧)
