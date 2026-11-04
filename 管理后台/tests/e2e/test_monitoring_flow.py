#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监测页对账(DF-04,2026-11-04;方案验收 C15「成功 / 失败 / 等待 / 取消 / 未知费用混合数据 → 指标、分母、未知范围可对账」)。

**自己造数据,不靠库里碰巧有什么**:在演示项目 B 里造一个只有这一份测试用的应用,7 次运行,形状覆盖每一类;
期望值全是**手算**的(下面注释里写着怎么算的),不拿被测代码现算。跑完删掉。

  r1 跑完 + 2 处写入都回执       → 办成            端到端 10 秒,费用 0.01
  r2 跑完 + 1 处回执 1 处没回执  → 跑完·没证实    20 秒,费用 0.02
  r3 跑完 + 没有写入             → 跑完·这次不需要写入   30 秒
  r4 失败                        → 失败            40 秒,费用 0.03 + 1 笔算不出金额
  r5 取消                        → 取消            50 秒
  r6 等人核对                    → 不算失败也不算成功
  r7 mock 跑完                   → 调试(默认的「业务」里不出现)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from sqlalchemy import create_engine, text

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_demo_b"
过, 挂 = [], []
应用 = "e2e_mon_" + uuid.uuid4().hex[:8]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 看(**筛):
    q = urllib.parse.urlencode({"天": 1, **筛})
    req = urllib.request.Request(f"{基址}/api/v1/projects/{项目}/monitoring?{q}", headers={"X-Dev-User": "U005"})   # 演示项目 B 的成员(种子数据里 U005 是它的编辑)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def main():
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    with 库.connect() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
    形 = [  # (编号, 状态, 跑法 mode, 秒, 写入 [状态...], 已知费用 [金额...], 算不出笔数)
        ("r1", "succeeded", "live", 10, ["已执行", "已执行"], [0.01], 0),
        ("r2", "succeeded", "live", 20, ["已执行", "待执行"], [0.02], 0),
        ("r3", "succeeded", "live", 30, [], [], 0),
        ("r4", "failed", "live", 40, [], [0.03], 1),
        ("r5", "cancelled", "live", 50, [], [], 0),
        ("r6", "waiting_approval", "live", None, [], [], 0),
        ("r7", "succeeded", "mock", 5, [], [], 0),
    ]
    ids = {}
    try:
        with 库.begin() as c:
            for 号, 态, 模式, 秒, 写们, 钱们, 算不出 in 形:
                rid, tid = f"xr_{应用}_{号}", f"tr_{应用}_{号}"
                ids[号] = rid
                c.execute(text("insert into traces (id, organization_id, project_id, created_at) values (:i,:o,:p, now())"),
                          {"i": tid, "o": org, "p": 项目})
                c.execute(text(f"""insert into execution_runs (id, organization_id, project_id, created_at, kind, status, execution_mode,
                                       environment, definition_ref, trace_id, started_at, ended_at)
                                   values (:i,:o,:p, now() - interval '2 minutes', 'workflow', :s, :m, 'development',
                                           cast(:d as jsonb), :t, now() - interval '100 seconds',
                                           {"now() - interval '100 seconds' + make_interval(secs => :sec)" if 秒 else "null"})"""),
                          {"i": rid, "o": org, "p": 项目, "s": 态, "m": 模式, "t": tid, "sec": 秒,
                           "d": json.dumps({"id": 应用, "version_no": 1, "环境": "production", "发起": "e2e"})})
                for j, w in enumerate(写们):
                    c.execute(text("""insert into bridge_calls (id, organization_id, project_id, created_at, execution_run_id,
                                          node_id, tool_name, idempotency_key, status)
                                      values (:i,:o,:p, now(), :r, :n, '写跟进', :k, :s)"""),
                              {"i": f"bc_{rid}_{j}", "o": org, "p": 项目, "r": rid, "n": f"n{j}", "k": f"{rid}:{j}", "s": w})
                for j, 钱 in enumerate(钱们):
                    c.execute(text("""insert into usage_ledger (id, organization_id, project_id, created_at, event_key, trace_id,
                                          resource, quantity, unit, currency, amount, amount_known)
                                      values (:i,:o,:p, now(), :k, :t, 'generate', 100, 'token', 'USD', :a, true)"""),
                              {"i": f"ul_{rid}_{j}", "o": org, "p": 项目, "k": f"{rid}:k{j}", "t": tid, "a": 钱})
                for j in range(算不出):
                    c.execute(text("""insert into usage_ledger (id, organization_id, project_id, created_at, event_key, trace_id,
                                          resource, quantity, unit, currency, amount, amount_known)
                                      values (:i,:o,:p, now(), :k, :t, 'generate', 50, 'token', 'USD', null, false)"""),
                              {"i": f"ul_{rid}_u{j}", "o": org, "p": 项目, "k": f"{rid}:u{j}", "t": tid})

        print("▸ 业务范围(默认)")
        c, d = 看(应用=应用)
        ck("200,筛选回显、带更新时刻", c == 200 and d["筛选"]["范围"] == "业务" and d.get("更新时刻"), (c, d))
        可, 业, 性, 本 = d["可用性"], d["业务"], d["性能"], d["成本"]
        # 业务范围 = r1..r6(r7 是 mock)→ 接收 6;终态 = r1..r5 = 5;跑完 = r1 r2 r3 = 3;终态成功率 = 3/5 = 60.0
        ck("接收 6(mock 那次不在业务里)、终态 5、跑完 3、等人核对 1", (可["接收"], 可["终态"], 可["跑完"], 可["等人核对"]) == (6, 5, 3, 1), 可)
        ck("**终态成功率 = 跑完 ÷ 已终结 = 3/5 = 60.0**(等人核对那次不进分母)", 可["终态成功率"] == 60.0 and 可["终态成功率分母"] == 5, 可)
        # 办成只有 r1;有写入的跑完 = r1 r2 → 写入办成率 = 1/2 = 50.0;r3 单列
        ck("**办成 1、跑完·没证实 1、这次不需要写入 1;写入办成率 = 1/2 = 50.0**(r3 不进分母)",
           (业["办成"], 业["跑完·没证实"], 业["跑完·这次不需要写入"], 业["写入办成率"], 业["写入办成率分母"]) == (1, 1, 1, 50.0, 2), 业)
        # 已知费用 = 0.01 + 0.02 + 0.03 = 0.06(含失败那次);算不出 1 笔 → 是至少;每个办成任务 = 0.06 / 1
        ck("**已知费用 0.06(含失败那次的钱)、算不出 1 笔 → 标「至少」**", abs(本["已知费用"] - 0.06) < 1e-9
           and 本["算不出金额的笔数"] == 1 and 本["是至少吗"] is True, 本)
        ck("**每个办成任务成本 = 所有运行的已知费用 ÷ 办成数 = 0.06**", abs((本["每个办成任务成本"] or 0) - 0.06) < 1e-9, 本)
        ck("token 合计 = 100×3 + 50 = 350", 本["token"] == 350, 本)
        # 端到端:终态的 5 次 = 10 20 30 40 50 秒 → P50 = 30;P95(线性插值)= 40 + 0.8×10 = 48
        ck("端到端 P50 = 30 秒、P95 = 48 秒(线性插值),5 条 → 标样本少", 性["端到端"] == {"样本数": 5, "P50秒": 30.0, "P95秒": 48.0, "样本少": True},
           性["端到端"])
        ck("分组里这个应用 v1:接收 6、办成 1、终态成功率 60.0", any(g["应用"] == 应用 and g["版本"] == 1 and g["接收"] == 6
                                                             and g["办成"] == 1 and g["终态成功率"] == 60.0 for g in d["分组"]), d["分组"])
        ck("说明里写着样本少、算不出金额", "样本" in d["note"] and "算不出" in d["note"], d["note"])

        print("\n▸ 调试范围 / 全部")
        c, d2 = 看(应用=应用, 范围="调试")
        ck("调试范围只有 mock 那一次(接收 1,跑完·这次不需要写入 1)", d2["可用性"]["接收"] == 1
           and d2["业务"]["跑完·这次不需要写入"] == 1, d2["可用性"])
        c, d3 = 看(应用=应用, 范围="全部")
        ck("全部 = 7", d3["可用性"]["接收"] == 7, d3["可用性"])

        print("\n▸ 未知不补零")
        c, d4 = 看(应用="没有这个应用_" + 应用)
        ck("**一次运行都没有 → 比例全是未知(None),每个办成任务成本未知,不写 0**",
           d4["可用性"]["接收"] == 0 and d4["可用性"]["终态成功率"] is None and d4["业务"]["写入办成率"] is None
           and d4["成本"]["每个办成任务成本"] is None and d4["性能"]["端到端"]["P50秒"] is None, d4)
        ck("说明里写着「未知,不是 0」", "不是 0" in d4["note"], d4["note"])
        c, b = 看(范围="瞎写")
        ck("范围写错 → 422", c == 422, (c, b))
    finally:
        with 库.begin() as c:
            for rid in ids.values():
                c.execute(text("delete from bridge_calls where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": rid})
                c.execute(text("delete from usage_ledger where project_id=:p and trace_id=:t"),
                          {"p": 项目, "t": rid.replace("xr_", "tr_", 1)})
                c.execute(text("delete from execution_runs where project_id=:p and id=:r"), {"p": 项目, "r": rid})
                c.execute(text("delete from traces where project_id=:p and id=:t"), {"p": 项目, "t": rid.replace("xr_", "tr_", 1)})

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 监测对账:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
