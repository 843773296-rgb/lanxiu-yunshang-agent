#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志采集策略端到端(11-14,用户拍业务拍板第四十条「用建议值」:保留 30 天 / 每项目 5 GB / 用到 80% 告警)。

验:没设时用建议值 · 四项都要填、越界 422、要 If-Match、没权限 403 · 用量只算正文列 ·
「到期会清哪些」只数早于保留期、正文还在的 · **到期清理开关关着 worker 一行不动**(清正文不可逆,默认关)·
打开后只清到期那几行、骨架留着、没到期的不动、再扫一遍不重复改 · 清了记审计 ·
告警比例改了,系统种的那条「日志用量占比」规则阈值跟着改 · 告警取值走同一把尺子 · 只给澜绣项目种规则。

**自己造数据**:在演示项目 B(隔离用的空项目)造一次运行 + 事件 / 步骤尝试各新旧两条,跑完删掉,策略列恢复原值。
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
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
标 = "e2e_logp_" + uuid.uuid4().hex[:8]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "services", "api", "app"))


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U001"):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
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
        org, 原策略 = c.execute(text("select organization_id, retention_policy from projects where id=:p"), {"p": 项目}).one()
    运行 = f"xr_{标}"
    事 = {k: f"ev_{标}_{k}" for k in ("旧", "新")}
    步 = {k: f"rs_{标}_{k}" for k in ("旧", "新")}
    规 = f"ar_{标}"
    import log_policy_api as LOGP
    import alerts_api as AL
    try:
        with 库.begin() as c:
            c.execute(text("""insert into execution_runs (id, organization_id, project_id, created_at, kind, status, execution_mode,
                                   environment, definition_ref, started_at, ended_at)
                               values (:i,:o,:p, now() - interval '41 days', 'workflow', 'succeeded', 'live', 'development',
                                       cast(:d as jsonb), now() - interval '41 days', now() - interval '41 days')"""),
                      {"i": 运行, "o": org, "p": 项目, "d": json.dumps({"id": 标, "version_no": 1, "发起": "e2e"})})
            for j, (k, 天) in enumerate((("旧", 40), ("新", 1))):
                c.execute(text(f"""insert into run_events (id, organization_id, project_id, created_at, execution_run_id, event_type,
                                       seq, payload, occurred_at)
                                   values (:i,:o,:p, now() - interval '{天} days', :r, 'step_succeeded', :s, cast(:pl as jsonb),
                                           now() - interval '{天} days')"""),
                          {"i": 事[k], "o": org, "p": 项目, "r": 运行, "s": j + 1,
                           "pl": json.dumps({"客户原话": "我要改袖长" * 50}, ensure_ascii=False)})
                c.execute(text(f"""insert into run_steps (id, organization_id, project_id, created_at, execution_run_id, node_id, kind,
                                       status, execution_key, input_ref, output_ref, error_detail)
                                   values (:i,:o,:p, now() - interval '{天} days', :r, 'n1', 'llm', 'succeeded', :ek, :in, null, null)"""),
                          {"i": 步[k], "o": org, "p": 项目, "r": 运行, "ek": f"{标}_{k}", "in": "顾客手机号 138xxxx " * 30})

        print("▸ 没设过 → 用建议值(30 天 / 5 GB / 80% / 到期清理关)")
        with 库.begin() as c:
            c.execute(text("update projects set retention_policy=null where id=:p"), {"p": 项目})
        c_, d = 打("GET", P + "/log-policy")
        ck("GET 200,来源「建议值」", c_ == 200 and d["来源"] == "建议值", (c_, d))
        ck("建议值就是拍板那三个数,到期清理默认关",
           d["策略"] == {"保留天数": 30, "容量上限GB": 5, "告警比例": 0.8, "到期清理": False}, d.get("策略"))
        ck("上限 = 5 GB 字节,告警线 = 上限 × 80%",
           d["用量"]["上限字节"] == 5 * 1024 ** 3 and d["用量"]["告警线字节"] == int(5 * 1024 ** 3 * 0.8), d["用量"])
        我的到期 = d["到期"]["各来源"]
        ck("**到期清单数到了我造的旧事件和旧步骤**(下限各 1 条)—— 「没到期的」和「一条都没数到」要分得开",
           我的到期["事件"]["条数"] >= 1 and 我的到期["步骤尝试"]["条数"] >= 1, 我的到期)
        用量前 = d["用量"]["字节"]
        ck("用量只算正文列:造的 4 条正文都算进去了(>0)", 用量前 > 0 and d["用量"]["各来源"]["事件"]["条数"] >= 2, d["用量"])

        print("\n▸ 改策略:四项都要、越界 422、要 If-Match、没权限 403")
        好 = {"保留天数": 30, "容量上限GB": 5, "告警比例": 0.6, "到期清理": False}
        c_, b = 打("PUT", P + "/log-policy", 好)
        ck("不带 If-Match → 409", c_ == 409 and b.get("code") == "IF_MATCH_REQUIRED", (c_, b))
        rev = str(d["revision"])
        c_, b = 打("PUT", P + "/log-policy", dict(好, 保留天数=3), {"If-Match": rev})
        ck("保留 3 天 → 422(7–365)", c_ == 422 and "保留天数" in (b.get("field_errors") or {}), (c_, b))
        c_, b = 打("PUT", P + "/log-policy", {k: v for k, v in 好.items() if k != "到期清理"}, {"If-Match": rev})
        ck("不给到期清理 → 422(不替人默认)", c_ == 422 and "到期清理" in (b.get("field_errors") or {}), (c_, b))
        c_, b = 打("PUT", P + "/log-policy", dict(好, 容量上限GB=True), {"If-Match": rev})
        ck("容量给 true → 422(布尔不当数字)", c_ == 422 and "容量上限GB" in (b.get("field_errors") or {}), (c_, b))
        c_, b = 打("PUT", P + "/log-policy", 好, {"If-Match": rev}, 谁="U005")
        ck("没「配置密钥与预算」权限 → 403", c_ == 403, (c_, b))

        with 库.begin() as c:   # 系统种的那条规则(演示项目 B 不在种子项目里,手动造一条 owner=system 的来验「跟着改」)
            c.execute(text("""insert into alert_rules (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                                  name, filter_snapshot, metric_code, direction_code, threshold_value, window_minutes, min_sample_count,
                                  trigger_count, recover_count, dedupe_minutes, owner, breach_count, normal_count)
                              values (:i,:o,:p, now(), 'system', now(), 1, :n, '{}'::jsonb, '日志用量占比', '高于', 79.9999, 1440, 1, 1, 1,
                                      1440, 'system', 0, 0)"""), {"i": 规, "o": org, "p": 项目, "n": f"e2e {标}"})
        c_, b = 打("PUT", P + "/log-policy", 好, {"If-Match": rev})
        ck("改成 告警比例 0.6 → 200,来源「已设置」", c_ == 200 and b["来源"] == "已设置" and b["策略"]["告警比例"] == 0.6, (c_, b))
        c_, b2 = 打("PUT", P + "/log-policy", 好, {"If-Match": rev})
        ck("拿旧 revision 再改 → 409(别人刚改过)", c_ == 409 and b2.get("code") == "REVISION_CONFLICT", (c_, b2))
        with 库.connect() as c:
            阈 = c.execute(text("select threshold_value from alert_rules where project_id=:p and id=:i"), {"p": 项目, "i": 规}).scalar()
            审 = c.execute(text("select count(*) from audit_events where project_id=:p and action='改日志采集策略' and at > now() - interval '5 minutes'"),
                          {"p": 项目}).scalar()
        ck("**系统那条「日志用量占比」规则阈值跟着变成 59.9999**(到 60% 就报)", float(阈) == 59.9999, 阈)
        ck("改策略记了审计", 审 >= 1, 审)

        print("\n▸ 告警取值:走同一把尺子;只给澜绣项目种规则")
        with 库.connect() as c:
            值, 样 = AL._外部取值("日志用量占比", c=c, project_id=项目)
            量 = LOGP.用量(c, 项目)["字节"]
            ck("取值 = 用量 / 5 GB × 100(和设置页同一份)", 样 == 1 and abs(值 - round(量 / (5 * 1024 ** 3) * 100, 4)) < 1e-9, (值, 样, 量))
        with 库.begin() as c:
            ck("演示项目 B 不在种子项目里 → 不种", AL.种上日志用量规则(c, 项目) == 0)

        print("\n▸ 到期清理开关关着 → worker 一行不动")
        话 = LOGP.扫到期()
        with 库.connect() as c:
            旧还在 = c.execute(text("select payload ? '客户原话' from run_events where project_id=:p and id=:i"), {"p": 项目, "i": 事["旧"]}).scalar()
        ck("**开关关着:我那条 40 天前的事件正文原样在**,扫到期() 没提这个项目", 旧还在 is True and not [x for x in 话 if 项目 in x], (旧还在, 话))

        print("\n▸ 打开到期清理 → 只清到期的,骨架留着,再扫不重复")
        c_, d2 = 打("GET", P + "/log-policy")
        c_, b = 打("PUT", P + "/log-policy", dict(好, 到期清理=True), {"If-Match": str(d2["revision"])})
        ck("打开到期清理 → 200", c_ == 200 and b["策略"]["到期清理"] is True, (c_, b))
        话 = LOGP.扫到期()
        我 = [x for x in 话 if 项目 in x]
        ck("扫到期() 清了这个项目(下限:至少 2 行 —— 我造的旧事件 + 旧步骤)", len(我) == 1 and "出错" not in 我[0], 话)
        with 库.connect() as c:
            e旧 = c.execute(text("select payload, event_type, seq from run_events where project_id=:p and id=:i"), {"p": 项目, "i": 事["旧"]}).one()
            e新 = c.execute(text("select payload from run_events where project_id=:p and id=:i"), {"p": 项目, "i": 事["新"]}).scalar()
            s旧 = c.execute(text("select input_ref, output_ref, status, execution_key from run_steps where project_id=:p and id=:i"), {"p": 项目, "i": 步["旧"]}).one()
            s新 = c.execute(text("select input_ref from run_steps where project_id=:p and id=:i"), {"p": 项目, "i": 步["新"]}).scalar()
            审 = c.execute(text("select count(*) from audit_events where project_id=:p and action='日志到期清理' and at > now() - interval '5 minutes'"),
                          {"p": 项目}).scalar()
        ck("**旧事件正文换成「到期删除」说明**,事件类型和序号(骨架)留着",
           "到期删除" in (e旧[0] or {}) and "客户原话" not in e旧[0] and e旧[1] == "step_succeeded" and e旧[2] == 1, e旧)
        ck("旧步骤的输入(text 列)换成占位,原来空的输出还是空(不凭空造一段),状态和执行键留着",
           (s旧[0] or "").startswith("[到期删除]") and s旧[1] is None and s旧[2] == "succeeded" and s旧[3] == f"{标}_旧", s旧)
        ck("**1 天前的事件和步骤一个字没动**", "客户原话" in (e新 or {}) and "138" in (s新 or ""), (e新, s新))
        ck("清了记审计「日志到期清理」", 审 >= 1, 审)
        话2 = LOGP.扫到期()
        ck("再扫一遍 → 这个项目不再改(已清的不重复清)", not [x for x in 话2 if 项目 in x], 话2)
        c_, d3 = 打("GET", P + "/log-policy")
        ck("清完用量降了", d3["用量"]["字节"] < 用量前, (用量前, d3["用量"]["字节"]))
        ck("清完到期清单里我造的那两条不再算", d3["到期"]["各来源"]["事件"]["条数"] == 我的到期["事件"]["条数"] - 1
           and d3["到期"]["各来源"]["步骤尝试"]["条数"] == 我的到期["步骤尝试"]["条数"] - 1, (我的到期, d3["到期"]))
    finally:
        with 库.begin() as c:
            c.execute(text("delete from run_events where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": 运行})
            c.execute(text("delete from run_steps where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": 运行})
            c.execute(text("delete from execution_runs where project_id=:p and id=:r"), {"p": 项目, "r": 运行})
            c.execute(text("delete from alert_incidents where project_id=:p and alert_rule_id=:r"), {"p": 项目, "r": 规})
            c.execute(text("delete from alert_rules where project_id=:p and id=:r"), {"p": 项目, "r": 规})
            c.execute(text("update projects set retention_policy=:v where id=:p"), {"v": 原策略, "p": 项目})
    print(f"\n{'✅' if not 挂 else '❌'} 日志采集策略:{len(过)} 过 / {len(挂)} 挂")
    sys.exit(1 if 挂 else 0)


if __name__ == "__main__":
    main()
