#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二个正式项目的门(2026-11-05;用户 11-04 拍「上第二个正式项目之前必须补好跨项目读取隔离」)。

迁移 9a6c1d3e7f42 声称这道门靠**结构**(库里的触发器)。一条从没被攻击过的结构性保证仍然只是约定 ——
所以这里**真去建一次**,每一刀都在一条回滚的事务里,库里什么都不留。

  ① 库里现在恰好一个没归档的正式项目(样本量:门要拦的前提)
  ② 再建一个正式项目 → 库拒,报错写明为什么、该做什么
  ③ 不标是哪种项目 → 库拒(必填、没有默认值 —— 不然新的正式项目会以「没标」的样子溜进来)
  ④ 把演示项目改成正式 → 库拒(不只拦插入)
  ⑤ 测试 / 演示项目 → 照建(e2e 要临时项目)
  ⑥ 钥匙:把「跨项目读隔离已结构化()」改成 true(补好隔离那个迁移会这么做)→ 第二个正式项目就建得了
"""
import os
import sys
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 引擎 as _引擎  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 试(sql, 参=None, 先=None):
    """在一条一定回滚的事务里执行 → ("成", None) / ("拒", 报错)。先 = 同一条事务里先跑的 SQL(比如换钥匙)。"""
    c = _引擎().connect()
    tx = c.begin()
    try:
        for x in (先 or []):
            c.execute(text(x))
        c.execute(text(sql), 参 or {})
        return "成", None
    except Exception as e:
        return "拒", str(e).split("\n")[0]
    finally:
        tx.rollback()
        c.close()


def main():
    c = _引擎().connect()
    try:
        org = c.execute(text("select organization_id from projects where id='project_lanxiu'")).scalar() \
            or c.execute(text("select id from organizations limit 1")).scalar()
        正式们 = c.execute(text("select id from projects where kind_code='正式' and archived_at is null")).scalars().all()
    finally:
        c.close()
    ck(f"① 库里恰好一个没归档的正式项目(门要拦的前提;现有:{正式们})", len(正式们) == 1, 正式们)

    新 = lambda: f"e2e_gate_{uuid.uuid4().hex[:8]}"   # noqa: E731
    建 = "insert into projects (id, organization_id, name, status, kind_code, created_at) values (:i, :o, 'e2e 门', 'active', :k, now())"

    结果, 错 = 试(建, {"i": 新(), "o": org, "k": "正式"})
    ck("② 再建一个正式项目 → 库拒,报错写明「跨项目读取隔离」和怎么开门",
       结果 == "拒" and "第二个正式项目" in (错 or "") and "隔离" in (错 or ""), (结果, 错))

    结果, 错 = 试("insert into projects (id, organization_id, name, status, created_at) values (:i, :o, 'e2e 门', 'active', now())",
                {"i": 新(), "o": org})
    ck("③ 不标是哪种项目 → 库拒(kind_code 必填、没有默认值)", 结果 == "拒" and "kind_code" in (错 or ""), (结果, 错))

    结果, 错 = 试("update projects set kind_code='正式' where id='project_demo_a'")
    ck("④ 把演示项目改成正式 → 库拒(门不只拦插入)", 结果 == "拒" and "第二个正式项目" in (错 or ""), (结果, 错))

    a, _ = 试(建, {"i": 新(), "o": org, "k": "测试"})
    b, _ = 试(建, {"i": 新(), "o": org, "k": "演示"})
    ck("⑤ 测试 / 演示项目照建(e2e 要临时项目)", (a, b) == ("成", "成"), (a, b))

    结果, 错 = 试(建, {"i": 新(), "o": org, "k": "正式"},
                 先=["create or replace function 跨项目读隔离已结构化() returns boolean language sql immutable as $$ select true $$"])
    ck("⑥ 钥匙换成 true(补好隔离那个迁移会这么做)→ 第二个正式项目建得了(门不是一律拒)", 结果 == "成", (结果, 错))

    c = _引擎().connect()
    try:
        还是关的 = c.execute(text("select 跨项目读隔离已结构化()")).scalar()
        留下 = c.execute(text("select count(*) from projects where id like 'e2e_gate_%'")).scalar()
    finally:
        c.close()
    ck("⑥ 试完钥匙照旧是 false、一个临时项目都没留下(每一刀都回滚了)", 还是关的 is False and 留下 == 0, (还是关的, 留下))

    # ⑦ 钥匙读的是判据,不是谁的一句话(并行会话 11-05 提的三条):钥匙是 true 的时候,下面三样必须都在 ——
    #    攻击判据文件在 / 它挂在门禁里 / 它在 bite_specs 里有咬合(「存在且挂着」≠「真会红」,咬合才是会红的凭据)
    import json as _json
    仓 = os.path.dirname(_根)
    攻击 = "tests/e2e/test_cross_project_read.py"
    在 = os.path.exists(os.path.join(_根, 攻击))
    # 查结构不查子串:那个文件名要出现在一条**真会执行的 recipe 行**上(tab 开头、去掉缩进后不以 # 开头)——
    # 子串的话,那一行被注释掉照样算「挂着」(并行会话 11-05 指出)
    挂门禁 = any(行.startswith("\t") and not 行.strip().startswith("#") and os.path.basename(攻击) in 行
               for 行 in open(os.path.join(_根, "Makefile"), encoding="utf-8").read().splitlines())
    咬合 = sum(1 for x in _json.load(open(os.path.join(仓, "tools", "bite_specs.json"), encoding="utf-8"))
             if x.get("script") == "管理后台/" + 攻击)
    if 还是关的 is False:
        print(f"  ℹ️ 钥匙关着(跨项目读隔离已结构化() = false)—— 开门那三样现在:攻击判据{'在' if 在 else '不在'} / "
              f"{'挂在' if 挂门禁 else '没挂'}门禁里 / 咬合 {咬合} 条。**这一条现在没在拦东西**,钥匙翻成 true 那天才拦")
    # 无条件断言(棘轮):原来写成「钥匙关着 or 三样都在」—— 钥匙恒关,右半边从不求值,这条恒绿,
    # 第一次真被求值的那天正是有人急着开门的那天(并行会话 11-05 指出)。三样今天都成立,所以每轮都真验
    ck("⑦ 开门那三样每轮都在:跨项目读取攻击判据在、挂在门禁的执行行上、至少 2 条咬合",
       在 and 挂门禁 and 咬合 >= 2, (在, 挂门禁, 咬合))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 第二个正式项目的门:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
