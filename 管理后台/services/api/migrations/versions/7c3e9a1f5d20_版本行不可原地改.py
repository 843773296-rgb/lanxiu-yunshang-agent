"""版本行不可原地改:提示词 / 工具 / 连接配置版本(DF-01 欠债,2026-11-05)

Revision ID: 7c3e9a1f5d20
Revises: 5e1a0c7d2b94
Create Date: 2026-11-05

## 为什么

「发生产要这一版用真模型跑通过」那道闸(用户 11-05 拍)认的是逻辑哈希。提示词 / 工具 / 连接按**版本 id**
钉在节点配置里、id 进哈希 —— 前提是**那个 id 指着的内容不会变**。这一条原来只是约定:契约里标着「不可变」
(contract/entities.py),库里什么都没拦。约定被违反时闸照样是绿的,而它保的已经是另一套行为。

## 做法:触发器,改了就失败

  · prompt_versions / tool_versions:内容列一列都不许改(只放过 updated_at / revision / archived_at —— 归档不改行为)
  · connection_versions:同上,**另外放过 capabilities / config_hash** —— 那是「探测」写的
    (connections_api 探一次把 capabilities 落到这一版上,这是设计好的那一处原地写)。
    探测改了 capabilities(里面有 execution_mode,worker 运行时读它定 mock / live)之后,
    闸靠**运行受理时记下的依赖指纹**判那次跑通还算不算数(workflows_api._依赖指纹),不靠这里

删除不拦:版本行被删,引用它的运行编译就失败,不会悄悄换一套行为跑。

⚠️ 触发器**不区分**「改别人的既有版本」和「回填自己刚插进去的那一行」。根目录 `fakedata/` 灌数据时
会先把环上的外键插空、全部插完再 UPDATE 回填(fakedata/load.py、apidrive.py)—— 所以它**不能直接打这个库**:
环上的外键要是牵到这三张表,回填会被这里打回,工厂停在插了一半、按 manifest 回滚。报错会指向这个触发器,
不是迁移坏了。(并行会话 11-05 指出;工厂现在只打 fakedata_test)
"""
from alembic import op

revision = "7c3e9a1f5d20"
down_revision = "5e1a0c7d2b94"
branch_labels = None
depends_on = None

# 表 → 允许原地改的列(其余任何一列变了都拒)
允许 = {
    "prompt_versions": ("updated_at", "revision", "archived_at"),
    "tool_versions": ("updated_at", "revision", "archived_at"),
    "connection_versions": ("updated_at", "revision", "archived_at", "capabilities", "config_hash"),
}


def upgrade():
    op.execute("""
        create or replace function 版本行不可原地改() returns trigger language plpgsql as $$
        declare 放过 text[] := tg_argv;
                旧 jsonb := to_jsonb(old);
                新 jsonb := to_jsonb(new);
                k text;
        begin
            foreach k in array 放过 loop
                旧 := 旧 - k; 新 := 新 - k;
            end loop;
            if 旧 is distinct from 新 then
                raise exception '% 是不可变版本:内容改了就要出一个新版本,不能原地改(id=%)', tg_table_name, old.id
                    using errcode = 'check_violation';
            end if;
            return new;
        end $$;
    """)
    for 表, 列 in 允许.items():
        参 = ", ".join(f"'{x}'" for x in 列)
        op.execute(f"drop trigger if exists trg_{表}_不可原地改 on {表}")
        op.execute(f"""create trigger trg_{表}_不可原地改 before update on {表}
                       for each row execute function 版本行不可原地改({参})""")


def downgrade():
    for 表 in 允许:
        op.execute(f"drop trigger if exists trg_{表}_不可原地改 on {表}")
    op.execute("drop function if exists 版本行不可原地改()")
