#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警端到端(DF-04 第二步,2026-11-04;方案验收 C16「低样本波动与持续异常 → 按最小样本、连续次数触发并恢复;
不重复轰炸;告警能下钻到运行」)。用户拍的判法:连续 N 次越线才报、连续 M 次正常才恢复、样本不够那轮不算。

**自己造数据**:演示项目 A 里一个只有这份测试用的应用(筛选按它),6 次运行;改它们的状态来模拟「坏了」「好了」。
期望值手算,判定那一份是 alert_rules.下一步(纯函数另有 test_alert_rules 验),这里验落库、接口、待办的开 / 提醒 / 恢复 / 处理。
跑完删掉自己造的;**留一条暂停着的样例规则**(ifmatch_reachable_check 要从列表拿 revision)。
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
项目 = "project_demo_a"
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
应用 = "e2e_alert_" + uuid.uuid4().hex[:8]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U001"):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法, data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def main():
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    with 库.connect() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
    ids, 规们 = [], []

    def 置状态(态):
        with 库.begin() as c:
            c.execute(text("update execution_runs set status=:s where project_id=:p and id = any(:ids)"), {"s": 态, "p": 项目, "ids": ids})

    def 评(rid):
        return 打("POST", P + f"/alert-rules/{rid}/evaluate", {})

    try:
        with 库.begin() as c:
            for j in range(6):
                rid = f"xr_{应用}_{j}"
                ids.append(rid)
                c.execute(text("""insert into execution_runs (id, organization_id, project_id, created_at, kind, status, execution_mode,
                                       environment, definition_ref, started_at, ended_at)
                                   values (:i,:o,:p, now() - interval '2 minutes', 'workflow', 'failed', 'live', 'development',
                                           cast(:d as jsonb), now() - interval '100 seconds', now() - interval '90 seconds')"""),
                          {"i": rid, "o": org, "p": 项目, "d": json.dumps({"id": 应用, "version_no": 1, "发起": "e2e"})})

        print("▸ 建规则:每一项都要填")
        规 = {"名字": f"e2e {应用} 成功率", "筛选": {"范围": "业务", "应用": 应用}, "指标": "终态成功率", "方向": "低于", "阈值": 90,
              "窗口分钟": 60, "最小样本": 5, "连续越线才报": 2, "连续正常才恢复": 2, "去重分钟": 60}
        c, b = 打("POST", P + "/alert-rules", {k: v for k, v in 规.items() if k != "阈值"})
        ck("不给阈值 → 422(产品配置,没有系统默认值)", c == 422 and "阈值" in (b.get("field_errors") or {}), (c, b))
        c, b = 打("POST", P + "/alert-rules", dict(规, 窗口分钟=1))
        ck("窗口 1 分钟 → 422(5–10080)", c == 422 and "窗口分钟" in (b.get("field_errors") or {}), (c, b))
        c, b = 打("POST", P + "/alert-rules", dict(规, 连续越线才报=0))
        ck("连续 0 次就报 → 422(那等于每轮都报)", c == 422, (c, b))
        c, b = 打("POST", P + "/alert-rules", 规, 谁="U005")
        ck("没有「配置密钥与预算」的建不了 → 403", c in (403, 404), (c, b))
        c, r = 打("POST", P + "/alert-rules", 规)
        ck("建好了", c == 201 and r.get("id"), (c, r))
        R = r["id"]; 规们.append(R)

        print("\n▸ 连续越线才报(N=2)")
        c, e1 = 评(R)
        ck("第 1 次:6 次运行全失败,终态成功率 0 < 90 → 不动(越线 1/2)", c == 200 and e1["动作"] == "不动" and e1["规则"]["连续越线"] == 1, e1)
        c, e2 = 评(R)
        ck("**第 2 次 → 开待办**", c == 200 and e2["动作"] == "开待办" and e2["规则"]["触发中"], e2)
        c, l = 打("GET", P + "/alert-incidents?status=触发中")
        我的 = [x for x in l.get("items", []) if x["规则"] == R]
        ck("站内待办里有 1 条触发中", len(我的) == 1, l)
        窗 = (我的[0] if 我的 else {}).get("开单那一窗") or {}
        ck("**待办带着开单那一窗:值 0.0、样本 6、窗口起止、筛选里是这个应用**(能下钻到那一窗的运行)",
           窗.get("值") == 0.0 and 窗.get("样本") == 6 and 窗.get("窗口起") and 窗.get("窗口止")
           and (窗.get("筛选") or {}).get("应用") == 应用, 窗)
        c, e3 = 评(R)
        ck("**第 3 次还越线,但在 60 分钟去重周期内 → 不动,不重复开单**", e3["动作"] == "不动", e3)
        c, l = 打("GET", P + "/alert-incidents?status=触发中")
        ck("还是只有 1 条触发中、又提醒 0 次", [x["又提醒了几次"] for x in l["items"] if x["规则"] == R] == [0], l)

        print("\n▸ 连续正常才恢复(M=2)")
        置状态("succeeded")
        c, e4 = 评(R)
        ck("好了 1 次(终态成功率 100)→ 还在触发中(正常 1/2)", e4["动作"] == "不动" and e4["规则"]["触发中"] and e4["规则"]["连续正常"] == 1, e4)
        c, e5 = 评(R)
        ck("**好了 2 次 → 恢复**,规则不再触发", e5["动作"] == "恢复" and not e5["规则"]["触发中"], e5)
        c, l = 打("GET", P + "/alert-incidents")
        那条 = [x for x in l["items"] if x["规则"] == R]
        ck("那条待办自动变成「已恢复」、带恢复时间", len(那条) == 1 and 那条[0]["状态"] == "已恢复" and 那条[0]["恢复时间"], 那条)

        print("\n▸ 再坏 → 开新的一条(历史留着);人工处理")
        置状态("failed")
        评(R); c, e6 = 评(R)
        ck("又连续越线 2 次 → 开第 2 条待办", e6["动作"] == "开待办", e6)
        c, l = 打("GET", P + "/alert-incidents")
        那些 = [x for x in l["items"] if x["规则"] == R]
        ck("这条规则一共 2 条待办:1 条已恢复(历史)+ 1 条触发中,触发中排前面",
           [x["状态"] for x in 那些] == ["触发中", "已恢复"], 那些)
        新 = 那些[0]["id"] if 那些 else None
        c, b = 打("POST", P + f"/alert-incidents/{新}/handle", {"说明": ""})
        ck("标已处理不写说明 → 422", c == 422, (c, b))
        c, b = 打("POST", P + f"/alert-incidents/{新}/handle", {"说明": "e2e:澜绣写入服务重启了"})
        ck("写了说明 → 已处理", c == 200 and b["状态"] == "已处理", (c, b))
        c, rl = 打("GET", P + "/alert-rules")
        这条 = next((x for x in rl["items"] if x["id"] == R), {})
        ck("**处理之后规则的连续次数清零、不再触发中**(问题没好的话,连续越线够了会重新开)", 这条.get("连续越线") == 0
           and not 这条.get("触发中"), 这条)
        c, b = 打("POST", P + f"/alert-incidents/{新}/handle", {"说明": "再标一次"})
        ck("已处理的再标 → 409", c == 409, (c, b))

        print("\n▸ 样本不够那一轮不算")
        c, r2 = 打("POST", P + "/alert-rules", dict(规, 名字=f"e2e {应用} 要 50 条", 最小样本=50, 连续越线才报=1))
        规们.append(r2["id"])
        c, e7 = 评(r2["id"])
        ck("**只有 6 条、最小样本 50 → 不动,连续越线不加**(样本不够不报)", e7["动作"] == "不动" and e7["规则"]["连续越线"] == 0
           and "最小样本" in e7["为什么"], e7)

        print("\n▸ worker 那条路径:真调 扫告警()(端到端上面走的是「立即评估」接口,worker 每 60 秒调的是这个)")
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                        "services", "api", "app"))
        import alerts_api as AL
        c, r3 = 打("POST", P + "/alert-rules", dict(规, 名字=f"e2e {应用} worker 路径", 连续越线才报=1))
        规们.append(r3["id"])
        话 = AL.扫告警()
        我的话 = [x for x in 话 if f"worker 路径" in x]
        ck("**扫告警() 真扫到了这条新规则(下限:至少 1 条),而且开了待办** —— 「这轮没有要报的」和「一条都没扫到」要分得开",
           len(我的话) == 1 and "开待办" in 我的话[0], 话)
        ck("这一轮没有规则评估出错", not [x for x in 话 if "出错" in x], 话)
        c, rl = 打("GET", P + "/alert-rules")
        ck("扫过之后它记下了上次评估时间(下一轮 5 分钟内不再评)",
           next((x for x in rl["items"] if x["id"] == r3["id"]), {}).get("上次评估"), rl)
        ck("紧接着再扫一次 → 这条不在里面(还没到 5 分钟)", not [x for x in AL.扫告警() if "worker 路径" in x])

        print("\n▸ 暂停")
        c, rl = 打("GET", P + "/alert-rules")
        rev = next((x["revision"] for x in rl["items"] if x["id"] == r2["id"]), None)
        c, b = 打("POST", P + f"/alert-rules/{r2['id']}/pause", {"暂停": True})
        ck("不带 If-Match → 409", c == 409, (c, b))
        c, b = 打("POST", P + f"/alert-rules/{r2['id']}/pause", {"暂停": True}, {"If-Match": str(rev)})
        ck("暂停 → 成", c == 200 and b["暂停了吗"] is True, (c, b))
    finally:
        with 库.begin() as c:
            if 规们:
                c.execute(text("delete from alert_incidents where project_id=:p and alert_rule_id = any(:r)"), {"p": 项目, "r": 规们})
                c.execute(text("delete from alert_rules where project_id=:p and id = any(:r)"), {"p": 项目, "r": 规们})
            c.execute(text("delete from execution_runs where project_id=:p and id = any(:ids)"), {"p": 项目, "ids": ids})
            # 留一条暂停着的样例规则(ifmatch_reachable_check 从列表拿 revision);重复跑不多出来
            if not c.execute(text("select 1 from alert_rules where project_id=:p and name='e2e 样例(可达性检查用)'"), {"p": 项目}).first():
                c.execute(text("""insert into alert_rules (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                                      name, filter_snapshot, metric_code, direction_code, threshold_value, window_minutes, min_sample_count,
                                      trigger_count, recover_count, dedupe_minutes, owner, breach_count, normal_count, paused_at)
                                  values (:i, :o, :p, now(), 'U001', now(), 1, 'e2e 样例(可达性检查用)', '{}'::jsonb, '终态成功率', '低于',
                                          90, 60, 5, 2, 2, 60, 'U001', 0, 0, now())"""),
                          {"i": "ar_e2e_sample", "o": org, "p": 项目})

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 告警:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
