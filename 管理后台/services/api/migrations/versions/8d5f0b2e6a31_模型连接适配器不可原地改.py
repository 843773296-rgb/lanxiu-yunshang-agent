"""模型连接:适配器 / 用途不可原地改(DF-01 欠债补一层,2026-11-05)

Revision ID: 8d5f0b2e6a31
Revises: 7c3e9a1f5d20
Create Date: 2026-11-05

7c3e9a1f5d20 管住了三张**版本**表,而 worker 运行时还读**父行** model_connections 的 adapter 和 status
(workers/worker.py 取模型连接那段)—— 逻辑哈希钉的是连接配置版本 id,父行变了哈希不变(并行会话 11-05 指出)。

  · adapter / purpose:换了就是另一套协议语义,而且**静默** —— 不许原地改,要换就新建一条连接
  · status / archived_at / display_name / updated_at / revision:停用、归档、改名是正常的管理动作,放过。
    停用之后「这一版跑通过」不再够发生产 —— 那一条由发生产的闸直接查(workflows_api.这一版跑通过吗:
    用到的连接有不是 active 的 → 不够),不靠触发器

同一个触发器函数(版本行不可原地改),参数是放过的列。
"""
from alembic import op

revision = "8d5f0b2e6a31"
down_revision = "7c3e9a1f5d20"
branch_labels = None
depends_on = None

放过 = ("updated_at", "revision", "archived_at", "status", "display_name")


def upgrade():
    参 = ", ".join(f"'{x}'" for x in 放过)
    op.execute("drop trigger if exists trg_model_connections_不可原地改 on model_connections")
    op.execute(f"""create trigger trg_model_connections_不可原地改 before update on model_connections
                   for each row execute function 版本行不可原地改({参})""")


def downgrade():
    op.execute("drop trigger if exists trg_model_connections_不可原地改 on model_connections")
