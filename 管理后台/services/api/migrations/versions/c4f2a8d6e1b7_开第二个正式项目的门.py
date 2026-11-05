"""开第二个正式项目的门:把「跨项目读隔离已结构化()」改成 true(用户 2026-11-05 拍「补完全绿就开」)

Revision ID: c4f2a8d6e1b7
Revises: b3e8f1c5a9d2
Create Date: 2026-11-06

9a6c1d3e7f42 装了门(触发器),钥匙恒 false:用户 11-04 拍「上第二个正式项目之前必须补好跨项目读取隔离」。
这一刀开门,凭的是判据,不是一句「补好了」:

  · 读:tests/e2e/test_cross_project_read.py 按真路由表攻 88 个带项目的 GET(列表 / 详情 / 查询串 / 库兜底)
  · 写:同一个文件攻 75 个路径带 id 的提交接口 + 请求体里塞别家运行号;tests/orchestration/test_write_project_scope.py
    扫每一句 UPDATE / DELETE 带不带 project_id
  · 咬合:读 3 条 + 提交 1 条,对照绿 → 改坏 → 红的是那一条(11-06 凌晨重放)
  · test_project_gate ⑦:钥匙是 true 时,上面那个攻击判据必须在、挂在门禁执行行上、至少 2 条咬合 —— 每轮都验

**没盖到的**(写进交接、报给用户,不是验过了):3 个 GET 不带查询参数就回 422、2 个 GET 和 10 个提交接口
在演示项目 A 里取不到它的 id。它们走的是同一套按 project_id 取数的写法,但这一轮没有被真攻到。

门本身留着:钥匙改回 false(downgrade)就重新关上。
"""
from alembic import op

revision = "c4f2a8d6e1b7"
down_revision = "b3e8f1c5a9d2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("create or replace function 跨项目读隔离已结构化() returns boolean language sql immutable as $$ select true $$")


def downgrade():
    op.execute("create or replace function 跨项目读隔离已结构化() returns boolean language sql immutable as $$ select false $$")
