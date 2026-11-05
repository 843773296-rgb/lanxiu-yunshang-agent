#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测派发(DF-05,2026-11-05;Dify 对标 §8.2 / C17「每版两轮、回执完整、超时有终态;不把排队登记当执行完成」)。

在演示项目 A 自己造:一条「开始 → 结束」工作流(不调模型、不花钱)出两版 + 一套 2 道题的冻结题集。

  ① 派发前就拦:超时 / 费用上限不填、候选不是工作流版本、候选 = 基线、题没有工作流输入 —— 都 422、都不建评测
  ② 派:2 题 × 候选 / 基线 × 2 轮 = 8 次运行,回执 8 条、(题, 边, 轮) 各一、跑法记成「评测」
  ③ **「已派发」不是「执行中」**:执行中一定有开始时间(至少一次子运行真的开始了)
  ④ **worker 自己收尾**(不手动调收一遍):等到「已完成」,逐题结果 8 条带边 / 轮,跑通分 8 条
  ⑤ 后台派发的不许外面再登记;已结束的取消不了
  ⑥ 超出费用上限:往一次子运行的 trace 上记一笔超上限的花费 → 收一遍 → 「超出费用上限」
  ⑦ 超时:挂一次永远不会被捞的运行,把「现在」拨过截止 → 收一遍 → 「超时」,那次运行被取消
  ⑧ 取消:要 If-Match、要理由;取消后「已取消」,再取消 → 409
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "jobs"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_demo_a"
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]
集名 = f"评测派发自测-{尾}"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U001", 头=None):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


def 错字段(d):
    return set(((d or {}).get("error") or d or {}).get("field_errors") or {})


from sqlalchemy import text            # noqa: E402
from db import 事务                     # noqa: E402
import eval_dispatch as ED             # noqa: E402


def 建工作流两版():
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 评测派发 {尾}", "模板": "空白"})
    wid = (w or {}).get("id")
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    定义["edges"] = [{"source": "start", "target": "finish", "port": "success"}]
    for n in 定义["nodes"]:
        if n["type"] == "end":
            n["config"]["bindings"] = {"summary": {"source": "input", "pointer": "/article"}}
    打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c1, v1 = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e 评测派发 基线"})
    # 候选那一版多输出一个「回显」—— 逻辑一样的两版出不了(NO_SEMANTIC_CHANGE)
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "end":
            n["config"]["output_schema"]["properties"]["回显"] = {"type": "string"}
            n["config"]["bindings"]["回显"] = {"source": "input", "pointer": "/article"}
    定义["output_schema"]["properties"]["回显"] = {"type": "string"}
    打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c2, v2 = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e 评测派发 候选"})
    return wid, (v1 or {}).get("id"), (v2 or {}).get("id"), (c1, v1, c2, v2)


def 造题集(题们):
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        did = f"ds_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into datasets (id, organization_id, project_id, name, format, purpose,
                              created_at, created_by, updated_at, revision)
                          values (:i,:o,:p,:n,'jsonl','评测', now(),'test', now(), 1)"""),
                  {"i": did, "o": org, "p": 项目, "n": 集名})
        冻 = []
        for 内容 in 题们:
            sid = f"smp_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into samples (id, organization_id, project_id, dataset_id, content, source,
                                  review_status, split, content_hash, created_at, created_by, updated_at, revision)
                              values (:i,:o,:p,:d, cast(:ct as jsonb), '自测', '已通过', '独立测试', :h,
                                      now(),'test', now(), 1)"""),
                      {"i": sid, "o": org, "p": 项目, "d": did, "h": uuid.uuid4().hex,
                       "ct": json.dumps(内容, ensure_ascii=False)})
            冻.append({"id": sid, "content": 内容})
        dv = f"dsv_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into dataset_versions (id, organization_id, project_id, dataset_id, split_map,
                              content_hash, sample_count, frozen_samples, created_at, created_by, revision)
                          values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n, cast(:fs as jsonb), now(),'test', 1)"""),
                  {"i": dv, "o": org, "p": 项目, "d": did, "h": uuid.uuid4().hex, "n": len(冻),
                   "sm": json.dumps({"独立测试": len(冻)}, ensure_ascii=False),
                   "fs": json.dumps(冻, ensure_ascii=False)})
    return dv, [x["id"] for x in 冻]


def 派(候选, 基线, dv, **改):
    体 = {"执行方式": "后台派发", "候选": 候选, "基线": 基线, "数据集版本": dv, "判据版本": "跑通-v1",
          "超时分钟": 30, "费用上限": 1}
    体.update(改)
    体 = {k: v for k, v in 体.items() if v is not None}
    return 打("POST", f"{P}/evaluations", 体, 头={"Idempotency-Key": uuid.uuid4().hex})


def 评测行(eid):
    with 事务() as c:
        return dict(c.execute(text("select * from evaluations where project_id=:p and id=:i"),
                              {"p": 项目, "i": eid}).mappings().first() or {})


def 清():
    with 事务() as c:
        eids = [r[0] for r in c.execute(text("""select e.id from evaluations e join dataset_versions v on v.id=e.dataset_version_id
                                                  join datasets d on d.id=v.dataset_id where d.name=:n"""), {"n": 集名})]
        c.execute(text("""delete from scores where evaluation_item_id in
                            (select id from evaluation_items where evaluation_id = any(:e))"""), {"e": eids})
        c.execute(text("delete from evaluation_items where evaluation_id = any(:e)"), {"e": eids})
        c.execute(text("delete from evaluation_runs where evaluation_id = any(:e)"), {"e": eids})
        c.execute(text("delete from evaluations where id = any(:e)"), {"e": eids})
        c.execute(text("""delete from dataset_versions where dataset_id in (select id from datasets where name=:n)"""), {"n": 集名})
        c.execute(text("""delete from samples where dataset_id in (select id from datasets where name=:n)"""), {"n": 集名})
        c.execute(text("delete from datasets where name=:n"), {"n": 集名})


def main():
    print("▸ 准备:一条「开始 → 结束」工作流出两版 + 2 道题的冻结题集")
    wid, 基线, 候选, 原 = 建工作流两版()
    ck("出了两版", bool(基线 and 候选 and 基线 != 候选), 原)
    dv, 题号 = 造题集([{"输入": {"article": "第 1 题"}}, {"输入": {"article": "第 2 题"}}])
    dv坏, _ = 造题集([{"输入": {"article": "好题"}}, {"问": "聊天形状的题", "答": "没有工作流输入"}])
    try:
        跑(wid, 基线, 候选, dv, dv坏, 题号)
    finally:
        清()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 评测派发:{len(过)} 条全过")
    return 0


def 跑(wid, 基线, 候选, dv, dv坏, 题号):
    print("\n▸ ① 派发前就拦(一个模型都没调)")
    with 事务() as c:
        前 = c.execute(text("select count(*) from evaluations where project_id=:p"), {"p": 项目}).scalar()
    s, b = 派(候选, 基线, dv, 超时分钟=None)
    ck("不填超时分钟 → 422(没有系统默认值)", s == 422 and "超时分钟" in 错字段(b), (s, b))
    s, b = 派(候选, 基线, dv, 费用上限=None)
    ck("不填费用上限 → 422", s == 422 and "费用上限" in 错字段(b), (s, b))
    s, b = 派(候选, 基线, dv, 费用上限=0)
    ck("费用上限 0 → 422(要大于 0)", s == 422 and "费用上限" in 错字段(b), (s, b))
    s, b = 派("按角色", 基线, dv)
    ck("候选不是工作流版本 → 422", s == 422 and "候选" in 错字段(b), (s, b))
    s, b = 派(候选, 候选, dv)
    ck("候选 = 基线 → 422", s == 422 and "基线" in 错字段(b), (s, b))
    s, b = 派(候选, 基线, dv坏)
    ck("**有一道题没有工作流输入 → 422,点名是哪道题**", s == 422 and any(k.startswith("题[") for k in 错字段(b)), (s, b))
    with 事务() as c:
        后 = c.execute(text("select count(*) from evaluations where project_id=:p"), {"p": 项目}).scalar()
    ck("上面这些一条评测都没建出来(整个事务回滚)", 后 == 前, (前, 后))

    print("\n▸ ② 派:2 题 × 2 边 × 2 轮")
    s, b = 派(候选, 基线, dv)
    eid = (b or {}).get("id")
    ck("派出去了:202、已派发、派了 8 次", s == 202 and b.get("status") == "已派发" and b.get("派了") == 8, (s, b))
    with 事务() as c:
        回 = [dict(x) for x in c.execute(text("""select er.*, x.definition_ref from evaluation_runs er
                    join execution_runs x on x.project_id=er.project_id and x.id=er.execution_run_id
                   where er.project_id=:p and er.evaluation_id=:e"""), {"p": 项目, "e": eid}).mappings()]
    ck("回执 8 条,(题, 边, 轮) 各一,每条指向不同的运行和任务",
       len(回) == 8 and len({(r["sample_id"], r["variant_code"], r["round_no"]) for r in 回}) == 8
       and len({r["execution_run_id"] for r in 回}) == 8 and len({r["job_id"] for r in 回}) == 8
       and {r["sample_id"] for r in 回} == set(题号), len(回))
    ck("子运行的跑法记成「评测」(写入只演练、监测页不算业务),而且带着是哪次评测",
       bool(回) and all((r["definition_ref"] or {}).get("跑法") == "评测" and (r["definition_ref"] or {}).get("评测", {}).get("id") == eid
           for r in 回), [r["definition_ref"] for r in 回[:1]])
    ck("候选那一边跑的是候选版本、基线那一边跑的是基线版本",
       bool(回) and all(r["workflow_version_id"] == (候选 if r["variant_code"] == "候选" else 基线) for r in 回))

    print("\n▸ ③「已派发」不是「执行中」")
    s, pg = 打("GET", f"{P}/evaluations/{eid}/progress")
    ck("进度能看:8 条回执、4 个分组(2 边 × 2 轮)", s == 200 and len(pg.get("回执", [])) == 8 and len(pg.get("分组", [])) == 4, (s, pg))
    ck("**状态是执行中时一定有开始时间**(排上队不算开始)",
       pg.get("status") == "已派发" or (pg.get("status") == "执行中" and pg.get("开始于")), pg.get("status"))

    print("\n▸ ④ worker 自己收尾(不手动调收一遍;worker 每 60 秒一遍)")
    终 = None
    for _ in range(150):
        终 = 评测行(eid)
        if 终.get("status") in ED.评测终态们:
            break
        time.sleep(1)
    ck("**worker 把它收成了「已完成」**(结束原因:全部收齐)",
       终.get("status") == "已完成" and 终.get("end_reason_code") == "ALL_COLLECTED", {k: 终.get(k) for k in ("status", "end_reason_code", "end_detail")})
    ck("开始时间、心跳、结束时间都有了,开始不早于派发", bool(终.get("started_at") and 终.get("heartbeat_at") and 终.get("ended_at"))
       and 终["started_at"] >= 终["dispatched_at"], {k: 终.get(k) for k in ("dispatched_at", "started_at", "heartbeat_at", "ended_at")})
    with 事务() as c:
        项 = [dict(x) for x in c.execute(text("""select i.*, s.dimension, s.value, s.value_known, s.source from evaluation_items i
                  left join scores s on s.evaluation_item_id=i.id where i.project_id=:p and i.evaluation_id=:e"""),
                  {"p": 项目, "e": eid}).mappings()]
        未收 = c.execute(text("select count(*) from evaluation_runs where project_id=:p and evaluation_id=:e and collected_at is null"),
                       {"p": 项目, "e": eid}).scalar()
    ck("逐题结果 8 条,每条带边 / 轮 / 运行,没有「外部登记」混进来",
       len(项) == 8 and {(x["variant_code"], x["round_no"]) for x in 项} == {("候选", 1), ("候选", 2), ("基线", 1), ("基线", 2)}
       and all(x["execution_run_id"] for x in 项), [(x["variant_code"], x["round_no"]) for x in 项])
    ck("每条一个「跑通」分(确定性规则、打了分),这条流程不调模型 → 全是 1",
       bool(项) and all(x["dimension"] == "跑通" and x["value_known"] and x["source"] == "确定性规则" and float(x["value"]) == 1 for x in 项),
       [(x["dimension"], x["value"]) for x in 项])
    ck("回执全部标了已收", bool(项) and 未收 == 0, 未收)
    s, pg = 打("GET", f"{P}/evaluations/{eid}/progress")
    ck("**每条回执都说得出执行者**(领走它的 worker)和开始时间", s == 200 and len(pg.get("回执", [])) == 8
       and all(x.get("执行者") and x.get("开始于") for x in pg["回执"]), (s, pg.get("回执", [])[:1]))
    ck("进度分组:每边每轮派 2 收 2、跑通率 1", s == 200 and len(pg.get("分组", [])) == 4
       and all(g["派了"] == 2 and g["已收"] == 2 and g["跑通率"] == 1 for g in pg["分组"]), pg.get("分组"))
    ck("逐题结果里存着运行的输出(能追回那次运行)",
       bool(项) and all((x["raw_output"] or {}).get("运行状态") == "succeeded" for x in 项), 项[:1] and 项[0]["raw_output"])

    print("\n▸ ⑤ 后台派发的不许外面登记;结束了取消不了")
    s, b = 打("POST", f"{P}/evaluations/{eid}/items", {"逐题": [{"样本": 题号[0], "原始输出": "x", "评分": []}]})
    ck("外面再登记 → 409 EVALUATION_DISPATCHED", s == 409 and 码(b) == "EVALUATION_DISPATCHED", (s, b))
    s, b = 打("POST", f"{P}/evaluations/{eid}/cancel", {"理由": "试试"}, 头={"If-Match": str(终.get("revision"))})
    ck("已完成的取消 → 409 EVALUATION_ENDED", s == 409 and 码(b) == "EVALUATION_ENDED", (s, b))

    print("\n▸ ⑥ 超出费用上限")
    s, b = 派(候选, 基线, dv, 费用上限=0.01)
    e2 = b["id"]
    with 事务() as c:
        r = c.execute(text("""select x.trace_id, x.organization_id from evaluation_runs er join execution_runs x
                               on x.project_id=er.project_id and x.id=er.execution_run_id
                              where er.project_id=:p and er.evaluation_id=:e limit 1"""), {"p": 项目, "e": e2}).mappings().first()
        c.execute(text("""insert into usage_ledger (id, organization_id, project_id, trace_id, amount, amount_known, currency,
                              quantity, unit, source, created_at, created_by)
                          values (:i, :o, :p, :t, 0.5, true, 'USD', 1, 'call', 'e2e评测派发', now(), 'test')"""),
                  {"i": f"ul_{uuid.uuid4().hex[:12]}", "o": r["organization_id"], "p": 项目, "t": r["trace_id"]})
    话 = ED.收一遍(项目)
    行 = 评测行(e2)
    ck("**已知花费 0.5 > 上限 0.01 → 超出费用上限**,说明里写着花了多少", 行.get("status") == "超出费用上限"
       and 行.get("end_reason_code") == "COST_CAP_EXCEEDED" and (行.get("end_detail") or {}).get("已知费用") == 0.5, (话, 行.get("end_detail")))
    with 事务() as c:
        c.execute(text("delete from usage_ledger where project_id=:p and source='e2e评测派发'"), {"p": 项目})

    print("\n▸ ⑦ 超时")
    s, b = 派(候选, 基线, dv, 超时分钟=1)
    e3 = b["id"]
    with 事务() as c:
        # 挂一次**永远不会被捞**的运行(没有任务)—— 模拟「派出去了,却一直没跑完」
        模 = c.execute(text("""select er.*, x.trace_id from evaluation_runs er join execution_runs x
                                on x.project_id=er.project_id and x.id=er.execution_run_id
                               where er.project_id=:p and er.evaluation_id=:e limit 1"""), {"p": 项目, "e": e3}).mappings().first()
        挂起 = f"xr_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into execution_runs (id, organization_id, project_id, kind, definition_ref, input_snapshot,
                              definition_hash, principal, status, environment, execution_mode, trace_id, idempotency_key,
                              created_at, created_by, updated_at, revision)
                          select :n, organization_id, project_id, kind, definition_ref, input_snapshot, definition_hash,
                                 principal, 'queued', environment, execution_mode, trace_id, :k, now(), 'test', now(), 1
                            from execution_runs where project_id=:p and id=:x"""),
                  {"n": 挂起, "k": f"e2e-挂起-{uuid.uuid4().hex}", "p": 项目, "x": 模["execution_run_id"]})
        c.execute(text("""insert into evaluation_runs (id, organization_id, project_id, evaluation_id, sample_id, variant_code,
                              round_no, workflow_version_id, execution_run_id, job_id, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, :e, :s, '候选', 3, :v, :x, 'job_不存在', now(), 'test', now(), 1)"""),
                  {"i": f"evr_{uuid.uuid4().hex[:12]}", "o": 模["organization_id"], "p": 项目, "e": e3,
                   "s": 模["sample_id"], "v": 模["workflow_version_id"], "x": 挂起})
    话 = ED.收一遍(项目, 现在=datetime.now(timezone.utc) + timedelta(minutes=2))
    行 = 评测行(e3)
    ck("**过了截止还有没跑完的 → 超时**,说明里点名没跑完的状态", 行.get("status") == "超时" and 行.get("end_reason_code") == "TIMEOUT"
       and "queued" in ((行.get("end_detail") or {}).get("没跑完的状态") or []), (话, 行.get("end_detail")))
    with 事务() as c:
        st = c.execute(text("select status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": 挂起}).scalar()
    ck("那次没跑完的运行被取消了(不是留着挂着)", st == "cancelled", st)

    print("\n▸ ⑧ 取消")
    s, b = 派(候选, 基线, dv)
    e4 = b["id"]
    s, x = 打("POST", f"{P}/evaluations/{e4}/cancel", {"理由": "e2e"})
    ck("不带 If-Match → 409", s == 409 and 码(x) == "IF_MATCH_REQUIRED", (s, x))
    rev = 评测行(e4)["revision"]
    s, x = 打("POST", f"{P}/evaluations/{e4}/cancel", {}, 头={"If-Match": str(rev)})
    ck("不写理由 → 422", s == 422 and "理由" in 错字段(x), (s, x))
    s, x = 打("POST", f"{P}/evaluations/{e4}/cancel", {"理由": "e2e 取消"}, 头={"If-Match": str(rev)})
    行 = 评测行(e4)
    ck("取消 → 已取消,理由和谁记在结束说明里", s == 200 and 行.get("status") == "已取消"
       and (行.get("end_detail") or {}).get("理由") == "e2e 取消", (s, x, 行.get("end_detail")))
    s, x = 打("POST", f"{P}/evaluations/{e4}/cancel", {"理由": "再来"}, 头={"If-Match": str(行["revision"])})
    ck("再取消 → 409 EVALUATION_ENDED", s == 409 and 码(x) == "EVALUATION_ENDED", (s, x))


if __name__ == "__main__":
    sys.exit(main())
