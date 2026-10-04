#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约和库一致吗(`alembic check` 的包装)—— **让它出现在我真会跑的那个目标里**。

## 为什么要包一层

`alembic check` 本来装在 `make test` 里(Makefile:78)。而这个仓库为
「判据装在没人跑的目标里」栽过三次,**三次都记在 Makefile 那段注释上**:

    · 10-01 `alembic check` 装在 make test 里,而我跑 contract/test-e2e
             —— 它从 09-29 起一直红而我不知道
    · 10-02 `ifmatch_reachable_check` 同一个形状,**一天拦我两次**
    · 10-04 **我第三次** —— 手工把七条约束写进迁移、没登记进
             `models._额外唯一`,本地 `make contract` + `./check.sh` 全绿、
             推了三次,而 CI 两次红在 `remove_constraint` 上

> **一条判据装在一个我从来没跑过的目标里,等于没装。**
> 而「本地没跑过」和「跑过并通过」,**在那份本地绿报告上长得一模一样。**

所以这一条进根 `check.sh` —— 那是我每次都跑的那个。

## 它为什么**可以**进门禁(而 make test 那一堆不行)

它只要一个**能连上的库**,不要服务在跑、不要 seed 过、不花钱。
而没有库的时候它报「**不适用**」并退 0 —— CI 的 admin-e2e 那边有库,
它在那儿是真跑的。

⚠️ 「不适用」**不是通过**,输出里会说清楚 ——
> 一条因为没库而跳过的检查,和一条真对齐了的,
> **在那个退出码上长得一模一样**,所以话必须说明白。

## 它抓的是哪一件事

`alembic check` 问的是「**契约模型和库的结构一致吗**」,而不是「迁移跑得通吗」。
这两件事差得很远:

> **autogenerate 做的是「让库跟上模型」—— 模型漏声明的时候,
> 它会安静地删掉一条真约束。**

所以手工写进迁移的唯一约束/索引,必须同时登记进 `app/models.py`
(`_额外唯一` 和那几条 `Index(...)`),否则下一次 autogenerate 会生成
一份**删掉它们**的迁移,而库「对齐」了、保护没了、一句话都不会报。
"""
# ── 咬合记录 ──────────────────────────────────────────────────────────
#
# 实测 2026-10-04,三关都验了:
#   ① 对照先绿                 → ✅ 契约和库一致
#   ② 从 `models._额外唯一` 里摘掉账本那条 → ❌
#   ③ **红的恰好点名那一条**    → `Detected removed unique constraint
#      'uq_task_budget_ledgers_project_id_task_ref' on 'task_budget_ledgers'`
#
# 第 ③ 关在这儿尤其便宜 —— alembic 自己就会点名。而它点名的那句话
# 正是「怎么读这个红」要引导的方向:**库里有而模型没声明**。
咬合 = [
    ("从 app/models.py 的 `_额外唯一` 里摘掉 task_budget_ledgers 那一条",
     "契约和库**不一致**"),
]

import os
import subprocess
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 管理后台/
API = os.path.join(根, "services", "api")
VENV = os.path.join(根, ".venv", "bin", "alembic")


def main():
    print("契约和库一致吗(alembic check)")
    print("=" * 76)
    if not os.path.exists(VENV):
        print(f"  ⏸ 没有 {VENV} —— **不适用,不是通过**(这台机器没装那个 venv)")
        return 0
    url = os.environ.get("DATABASE_URL") or (
        f"postgresql+psycopg://{os.environ.get('USER','')}@localhost:5432/aimc_dev")
    env = dict(os.environ, DATABASE_URL=url)
    # ⚠️ **不接管道** —— 管道会吞掉退出码,而这个仓库为这件事栽过
    # (Makefile 里 `node ... | tail -1` 让页面冒烟红了也不拦)。
    p = subprocess.run([VENV, "check"], cwd=API, env=env,
                       capture_output=True, text=True)
    出 = (p.stdout or "") + (p.stderr or "")
    连不上 = any(k in 出 for k in (
        "could not connect", "does not exist", "Connection refused",
        "OperationalError"))
    if p.returncode != 0 and 连不上:
        # 没库 → 不适用。**说清楚**,别让它看着像通过。
        print(f"  ⏸ 连不上库({url.rsplit('/', 1)[-1]})—— "
              f"**不适用,不是通过**。CI 的 admin-e2e 那边有库,它在那儿真跑")
        print("     ⚠️ 一条因为没库而跳过的检查,和一条真对齐了的,"
              "**在那个退出码上长得一模一样**")
        return 0
    if p.returncode != 0:
        print("  ❌ 契约和库**不一致**:")
        for l in 出.strip().splitlines()[-6:]:
            print("    ", l[:300])
        print("\n  怎么读这个红:")
        print("    · 报 `remove_constraint` / `remove_index` → "
              "**库里有而模型没声明** —— 多半是手工写进迁移、"
              "忘了登记进 `app/models.py` 的 `_额外唯一` 或那几条 `Index(...)`")
        print("    · 报 `add_*` → 契约改了而迁移没补 —— `make migrate m=\"...\"`")
        print("  ⚠️ **别靠 autogenerate 来「对齐」** —— 它会生成一份"
              "**删掉那条真约束**的迁移,照着跑库就对齐了,而保护没了,"
              "一句话都不会报")
        return 1
    print("  ✅ 契约和库一致(No new upgrade operations detected)")
    print("     ⚠️ 它问的是「**结构一致吗**」,不是「迁移跑得通吗」——"
          "后者由 CI 的 `alembic upgrade head` 从零验")
    return 0


if __name__ == "__main__":
    sys.exit(main())
