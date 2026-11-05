"""第二个正式项目的门:跨项目读取隔离补好之前,库里只许有一个正式项目(2026-11-05)

Revision ID: 9a6c1d3e7f42
Revises: 8d5f0b2e6a31
Create Date: 2026-11-05

## 为什么

用户 11-04 拍:管理后台跨项目**读取**隔离现在是「约定」(新接口全靠人记得补攻击用例,漏了不会有任何东西红),
**上第二个正式项目之前必须补好**。当时我提议「开新项目那一步加一道闸」—— 不装的话,「之前必须补好」又只是一句约定。

## 做法

  · projects 加 kind_code(正式 / 演示 / 测试),**必填、没有默认值** —— 建项目的地方都得说清是哪一种,
    不然一个新的正式项目会以「没标」的样子溜进来。老行回填:project_demo_* → 演示,其余 → 正式(现在就是 project_lanxiu)
  · 触发器:插入 / 改成正式时,如果「跨项目读隔离已结构化()」还是 false,而库里已经有另一个没归档的正式项目 → 拒,
    报错里写明为什么、该做什么
  · 「跨项目读隔离已结构化()」现在恒 false。**补好隔离的那个迁移把它改成 true**(create or replace function)——
    门在库里,开门的钥匙也在库里,不靠谁记得

演示 / 测试项目不受限:e2e 要建临时项目、演示项目要留着验隔离。

⚠️ **开门不许是一行 `select true`。** 将来有人急着上第二个正式项目时,这个函数就是挡路的那一个 ——
翻成 true 的成本是一行,验证隔离真做好了的成本是一周(并行会话 11-05 指出:「真做好了」和「为了解开闸改成 true」
在这道闸上长得一模一样)。所以 tests/e2e/test_project_gate.py 另守一条:**钥匙是 true 的时候,
跨项目读取的攻击判据必须在、而且挂在门禁里** —— 钥匙读的是那条判据,不是谁的一句话。
现存数也盯着:那份测试第一条断言「现在恰好一个没归档的正式项目」,回填多标一个就红。
"""
from alembic import op

revision = "9a6c1d3e7f42"
down_revision = "8d5f0b2e6a31"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table projects add column kind_code text")
    op.execute("update projects set kind_code = case when id like 'project\\_demo\\_%' then '演示' else '正式' end")
    op.execute("alter table projects alter column kind_code set not null")
    op.execute("alter table projects add constraint ck_projects_kind check (kind_code in ('正式', '演示', '测试'))")
    op.execute("""
        create or replace function 跨项目读隔离已结构化() returns boolean language sql immutable as $$ select false $$;
    """)
    op.execute("""
        create or replace function 第二个正式项目的门() returns trigger language plpgsql as $$
        begin
            if new.kind_code = '正式' and new.archived_at is null and not 跨项目读隔离已结构化()
               and exists (select 1 from projects p where p.kind_code = '正式' and p.archived_at is null and p.id <> new.id) then
                raise exception '还不能建第二个正式项目(%)—— 管理后台跨项目读取隔离还是约定,用户 11-04 拍了上第二个正式项目之前必须补好。先做隔离;做完那个迁移会把 跨项目读隔离已结构化() 改成 true。演示 / 测试项目不受限(kind_code 填 演示 / 测试)', new.id
                    using errcode = 'check_violation';
            end if;
            return new;
        end $$;
    """)
    op.execute("""create trigger trg_projects_第二个正式项目的门 before insert or update of kind_code, archived_at on projects
                  for each row execute function 第二个正式项目的门()""")


def downgrade():
    op.execute("drop trigger if exists trg_projects_第二个正式项目的门 on projects")
    op.execute("drop function if exists 第二个正式项目的门()")
    op.execute("drop function if exists 跨项目读隔离已结构化()")
    op.execute("alter table projects drop constraint if exists ck_projects_kind")
    op.execute("alter table projects drop column if exists kind_code")
