#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连接指纹换算法的过渡期(用户 2026-11-06 拍「改,只算能力项」)—— 库里那一层。纯函数那层在 test_step_freshness_check ⑫。

  ① **这一轮自己受理的那一次运行,记下的连接指纹全是新算法**(带 v2: 前缀);有人把受理改回老算法 → 红。
     「切换之后库里所有运行」那个数只打印:共享库里另一份没拉新代码的检出照旧写老算法,那不是这份代码的事
  ② 反向检查(棘轮,只许降不许涨):「只靠老算法才对得上」的成功运行有几条。老值不会再新增(①管着),
     这个数只会随着重探 / 版本更替往下走;降了印一句「把上限改成 N」,**降到 0 印「可以把老算法摘了」**
     —— 摘不摘由人定,但「什么时候能摘」不靠谁记得回来看(并行会话 11-06 提的:过渡期开关一旦没人回来摘,就永久接受老算法)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in (("services", "api", "app"), ("services", "api", "app", "runtime"), ("services", "api", "app", "contract")):
    sys.path.insert(0, os.path.join(根, *p))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import release as RL  # noqa: E402
import workflows_api as WA  # noqa: E402

切换时刻 = "2026-11-06 11:23:30+0800"     # 新算法随 aimc 重启上线(11-06 11:23:15 锁里重启)之后
上限 = 561                              # 11-06 量的:记了指纹的成功运行 550 条,全部只靠老算法对得上
# ⚠️ 11-12 550 → 561 不是放宽,是**改正量错的基线**:11-06 量的时候,test_runctl_flow 已经从 10-24 起
# 把成功运行一条条改成 running 不还原(执行手册 W06),那批不在「status='succeeded'」里,所以 550 少数了。
# 11-12 用 tools/fix_test_residue_runs.py 还原后多出的 11 条:**全部带 run.data_fix 事件、全部建于切换时刻之前**
# (查询见那次提交说明)—— 没有一条是切换之后新写的老算法。「老值不再新增」由 ① 管着,没动。
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 受理一次():
    """自己受理一次(不靠库里碰巧有切换之后的运行 —— 空集合上「全是新算法」自动成立)。
    找一条最近记过指纹的草稿运行,沿用它上次的输入,在**测试进程里**调受理接口(TestClient:咬合改坏受理那段时在视野里)。"""
    import uuid
    from fastapi.testclient import TestClient
    import main as _M
    with 事务() as c:
        r = c.execute(text("""select project_id, id, definition_ref->>'id' wid from execution_runs
                               where kind='workflow' and definition_ref->>'kind'='graph_draft' and definition_ref ? '依赖指纹'
                                 and status='succeeded' and project_id='project_demo_a'
                               order by created_at desc limit 1""")).mappings().first()
    if not r:
        return None, "演示项目里没有记过指纹的草稿运行"
    rs = TestClient(_M.app).post(f"/api/v1/projects/{r['project_id']}/execution-runs",
                                 headers={"X-Dev-User": "U002", "Idempotency-Key": str(uuid.uuid4())},
                                 json={"workflow_id": r["wid"], "沿用运行": r["id"]})
    if rs.status_code != 202:
        return None, f"受理 {rs.status_code}:{rs.text[:200]}"
    with 事务() as c:
        fp = c.execute(text("select definition_ref->'依赖指纹' from execution_runs where project_id=:p and id=:i"),
                       {"p": r["project_id"], "i": rs.json()["resource_id"]}).scalar()
    return fp, None


def main():
    fp, 为什么 = 受理一次()
    连接项 = {k: v for k, v in (fp or {}).items() if not k.startswith("tool:")}
    ck("① 这一轮自己受理的运行:连接指纹全是新算法(带 v2: 前缀)",
       bool(连接项) and all(str(v).startswith(WA.指纹前缀) for v in 连接项.values()), 为什么 or fp)
    with 事务() as c:
        新 = c.execute(text("""select id, definition_ref->'依赖指纹' fp from execution_runs
                               where kind='workflow' and definition_ref ? '依赖指纹' and created_at >= cast(:t as timestamptz)"""),
                      {"t": 切换时刻}).mappings().all()
        老式 = [(r["id"], k) for r in 新 for k, v in (r["fp"] or {}).items()
                if not k.startswith("tool:") and v and not str(v).startswith(WA.指纹前缀)]
        print(f"  ℹ️ 切换之后受理、记了指纹的运行:{len(新)} 条")
        # 只打印、不判红(11-06 第一次整轮就撞到):共享库里还有别的检出在写运行 —— 没拉新代码的那份照旧按老算法记,
        # 红不红取决于「另一份检出拉没拉代码」,不是在验这份代码。判据是上面那条(这一轮自己受理的那一次)
        print(f"  ℹ️ 切换之后按老算法记的:{len(老式)} 条(**不是判据**;多半来自还没拉新代码的另一份检出){(' 例:' + str(老式[:2])) if 老式 else ''}")

        rs = c.execute(text("""select project_id, definition_ref->'依赖指纹' fp from execution_runs
                                where kind='workflow' and status='succeeded' and definition_ref ? '依赖指纹'""")).mappings().all()
        n = 0
        for r in rs:
            fp = r["fp"] or {}
            要 = list(fp)
            n += RL.靠旧算法的(fp, WA._依赖指纹(c, r["project_id"], 要), 要,
                             旧=WA._依赖指纹旧(c, r["project_id"], [x for x in 要 if not x.startswith("tool:")]))
    print(f"  ℹ️ 记了指纹的成功运行 {len(rs)} 条,其中只靠老算法才对得上的 {n} 条(上限 {上限})")
    ck("② 只靠老算法才对得上的成功运行只许降不许涨(棘轮)", n <= 上限, (n, 上限))
    if n < 上限:
        print(f"  ℹ️ 降了:把本文件的 上限 改成 {n}(棘轮跟着走,不然空档会越拉越大)")
    if n == 0:
        print("  ℹ️ **已经没有靠老算法的记录了 —— 可以把 workflows_api._依赖指纹旧 和 release.依赖没变吗 里认老值那一支摘了**")
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 连接指纹换算法的过渡期:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
