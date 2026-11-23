#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工介入表单化 · 端到端(四期 4-1,11-20 夜;照 Dify:说明 + 字段 + 按钮,每个按钮一个出口)。

打真起着的 :8801(U001)。流程:开始(摘要)→ 店长判责(两个按钮:顾客责任 / 门店责任;字段 备注、赔付(下拉必填))
→ 顾客责任 → 模板「顾客:…」/ 门店责任 → 模板「门店:…」→ 变量聚合器 → 结束。不调模型。
  ① 建图、检查配置无阻断(按钮都接了线)
  ② 发起运行 → 停在等人核对;待办详情的「核对材料.__表单」带说明(已渲染)、字段、按钮;allowed_fields 里有字段名
  ③ 决定 = 不认识的按钮 → 422;决定 = 「门店责任」+ 字段 → 201,运行恢复、走门店那一路,输出带 门店:门店责任
  ④ 两个人同时点:第二个拿旧 revision → 409 REVISION_CONFLICT(库约束级,不只靠接口 if)
  ⑤ 决定历史里记的是按钮 id;待办状态 approved(有结论)
  ⑥ 收尾:归档
飞书通知那条没在这儿验(要一个真的群机器人);接线由 worker 的 _飞书通知 + 通知文本 守,推不出去只记事件不影响运行。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, _这)
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import _模型模式 as MM  # noqa: E402
import _清成员 as 成员  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
P = f"/api/v1/projects/{项目}"
PY = os.path.join(根, ".venv", "bin", "python")
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    h = {"X-Dev-User": 谁, "Content-Type": "application/json", **(头 or {})}
    rq = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法, headers=h,
                                data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


服务是mock = MM.模型是mock(基址)


def 跑worker():
    import subprocess
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"], capture_output=True, text=True, timeout=240, cwd=根,
                   env=dict(os.environ, MODEL_ADAPTER=("mock" if 服务是mock else "anthropic")))


def 状态(rid):
    with 事务() as c:
        return c.execute(text("select status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()


def 等到(rid, 要的, 最多=20):
    for _ in range(最多):
        s = 状态(rid)
        if s in 要的:
            return s
        跑worker()
        time.sleep(0.5)
    return 状态(rid)


建的 = []


def 收尾():
    for wid in list(建的):
        c, b = 打("POST", P + f"/workflows/{wid}/archive", 体={"理由": "e2e 收尾"})
        if c != 200:
            print(f"  ⚠️ 收尾没归档成 {wid}:{c} {b}")
    建的.clear()


def main():
    print("▸ ① 建图:开始 → 店长判责(两个按钮)→ 两路模板 → 聚合 → 结束")
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 人工表单 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = (w or {}).get("id")
    建的.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    模板 = lambda i, 字: {"id": i, "type": "template", "name": i, "config": {"template": 字 + "{{谁}}", "bindings": {"谁": {"source": "node", "node_id": "核", "pointer": "/__action_id"}}}}  # noqa: E731
    定义["nodes"] = [
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": {"type": "object", "properties": {"摘要": {"type": "string"}, "门店": {"type": "string"}}, "required": ["摘要"]}}},
        {"id": "核", "type": "human", "name": "店长判责", "config": {
            "request_kind": "核对", "candidate_roles": ["admin"], "expires_at_policy": {"小时": 24, "到期": "fail"},
            "payload_binding": {"摘要": {"source": "input", "pointer": "/摘要"}},
            "form_markdown": "客户说:**{{摘要}}**。请判断责任方。",
            "form_fields": [{"name": "备注", "title": "备注", "type": "段落", "required": False}, {"name": "赔付", "title": "赔付方式", "type": "下拉", "options": ["退款", "换货"], "required": True}],
            "actions": [{"id": "顾客责任", "文字": "顾客责任", "样式": "默认"}, {"id": "门店责任", "文字": "门店责任", "样式": "强调"}]}},
        模板("甲路", "顾客:"), 模板("乙路", "门店:"),
        {"id": "汇", "type": "merge", "config": {"candidates": [{"source": "node", "node_id": "甲路", "pointer": "/文本"}, {"source": "node", "node_id": "乙路", "pointer": "/文本"}], "output_field": "out"}},
        {"id": "finish", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "汇", "pointer": "/out"}}}}]
    定义["edges"] = [{"source": "start", "target": "核", "port": "success"},
                   {"source": "核", "target": "甲路", "port": "branch", "branch_key": "顾客责任"},
                   {"source": "核", "target": "乙路", "port": "branch", "branch_key": "门店责任"},
                   {"source": "甲路", "target": "汇", "port": "success"}, {"source": "乙路", "target": "汇", "port": "success"},
                   {"source": "汇", "target": "finish", "port": "success"}]
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    阻 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("存草稿 200 · 检查配置无阻断(两个按钮都接了线、字段没重名)", c == 200 and c2 == 200 and 阻 == [], (c, b, c2, 阻, vb))

    print("\n▸ ② 发起运行 → 停下等人;待办详情带表单")
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"摘要": "袖子短了"}})
    rid = (r or {}).get("resource_id")
    st = 等到(rid, ("waiting_approval", "failed", "succeeded", "cancelled")) if rid else None
    ck("受理 202、停在 waiting_approval", c == 202 and st == "waiting_approval", (c, r, st))
    with 事务() as cx:
        hid = cx.execute(text("select id from human_requests where project_id=:p and execution_run_id=:r order by created_at desc limit 1"), {"p": 项目, "r": rid}).scalar()
    c, 详 = 打("GET", P + f"/human-requests/{hid}") if hid else (None, None)
    表 = ((详 or {}).get("核对材料") or {}).get("__表单") or {}
    ck("待办详情.核对材料.__表单:说明已渲染(带「袖子短了」)、两个按钮、两个字段", c == 200 and "袖子短了" in (表.get("说明") or "")
       and [a["id"] for a in 表.get("按钮", [])] == ["顾客责任", "门店责任"] and [f["name"] for f in 表.get("字段", [])] == ["备注", "赔付"], (c, 表))
    ck("允许编辑的字段里有 备注 / 赔付", {"备注", "赔付"} <= set((详 or {}).get("允许编辑的字段") or []), (详 or {}).get("允许编辑的字段"))
    rev = ((详 or {}).get("请求") or {}).get("revision")

    print("\n▸ ③ 决定")
    c, b = 打("POST", P + f"/human-requests/{hid}/decisions", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"decision": "不存在的按钮", "request_revision": rev, "edits": {}})
    ck("不认识的按钮 → 422", c == 422, (c, b))
    c, b = 打("POST", P + f"/human-requests/{hid}/decisions", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"decision": "门店责任", "request_revision": rev, "edits": {"赔付": "退款", "备注": "袖长差 2 厘米"}})
    ck("按钮「门店责任」+ 字段 → 201,记的决定就是按钮 id、状态 approved(有结论)、排了恢复",
       c == 201 and (b or {}).get("decision") == "门店责任" and (b or {}).get("当前状态") == "approved" and (b or {}).get("运行"), (c, b))
    st = 等到(rid, ("succeeded", "failed", "cancelled", "incomplete"))
    with 事务() as cx:
        行 = cx.execute(text("select output_ref, status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).mappings().first()
        步 = cx.execute(text("select node_id, status, branch_key, output_ref from run_steps where project_id=:p and execution_run_id=:i order by created_at"), {"p": 项目, "i": rid}).mappings().all()
    出 = (行 or {}).get("output_ref") or {}
    if isinstance(出, str):
        出 = json.loads(出)
    ck("运行跑成,走的是门店那一路:输出 text = 门店:门店责任", st == "succeeded" and 出.get("text") == "门店:门店责任", (st, 出, [(x["node_id"], x["status"], x["branch_key"]) for x in 步]))
    核 = [x for x in 步 if x["node_id"] == "核" and x["status"] == "succeeded"]
    核出 = (核[-1]["output_ref"] if 核 else {}) or {}
    if isinstance(核出, str):
        核出 = json.loads(核出)
    ck("核这一步的输出带 __action_id=门店责任、赔付=退款、备注", 核出.get("__action_id") == "门店责任" and 核出.get("赔付") == "退款" and 核出.get("备注") == "袖长差 2 厘米", 核出)

    print("\n▸ ④ 两个人同时点:第二个拿旧 revision → 409")
    c, b = 打("POST", P + f"/human-requests/{hid}/decisions", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"decision": "顾客责任", "request_revision": rev, "edits": {"赔付": "换货"}})
    ck("旧 revision → 409 REVISION_CONFLICT(不覆盖第一个人的决定)", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))

    print("\n▸ ⑤ 决定历史")
    c, 详 = 打("GET", P + f"/human-requests/{hid}")
    历 = (详 or {}).get("决定历史") or []
    ck("决定历史一条,decision=门店责任;待办状态 approved", len(历) == 1 and 历[0].get("decision") == "门店责任" and ((详 or {}).get("请求") or {}).get("status") == "approved", (历, ((详 or {}).get("请求") or {}).get("status")))

    print("\n▸ ⑥ 按门店分开(11-21 用户拍:店长只看到、只处理本店的单子)")
    尾 = uuid.uuid4().hex[:5].upper()
    甲 = 成员.记(项目, f"E2EHS1{尾}")   # SH001 的店长(管理员角色才在 candidate_roles 里)
    乙 = 成员.记(项目, f"E2EHS2{尾}")   # SH002 的店长
    # 「审批工具动作」对 admin 是「可授权」档、默认关 —— 要显式专项授权,不然决定那一步先被 403 拦住、到不了门店范围的 404(第八轮 e2e 栽过)。
    # 11-24:**授权直接写库,不走邀请接口** —— GitHub CI 的新库里 U001 自己没有「审批工具动作」,带着「专项授权」去 POST 会 422 CANNOT_GRANT
    # (规则「不能通过邀请获得自己没有的权限」是对的,是夹具的事;11-19 起 CI 这份一直红在这、没人看见)。照 test_chat_annotations_flow 的做法。
    c1, b1 = 打("POST", P + "/memberships", 体={"工号": 甲, "角色": "admin", "门店": "sh001"})
    c2, b2 = 打("POST", P + "/memberships", 体={"工号": 乙, "角色": "admin", "门店": "SH002"})
    with 事务() as c:
        n授 = c.execute(text("update memberships set special_grants = cast(:g as jsonb) where project_id=:p and user_id in (:a, :b) and user_id like 'E2E%'"),
                       {"g": json.dumps(["审批工具动作"]), "p": 项目, "a": 甲, "b": 乙}).rowcount
    ck("加两个临时成员,各登记一个门店(编号统一成大写);「审批工具动作」直接写库授权 2 行", c1 == 201 and c2 == 201 and (b1 or {}).get("门店") == "SH001" and (b2 or {}).get("门店") == "SH002" and n授 == 2,
       (c1, b1, c2, b2, n授))
    c, m = 打("GET", P + "/memberships")
    行 = {x["工号"]: x for x in (m or {}).get("成员") or []}
    ck("成员列表里带门店;老成员没登记 = 不限门店(None)", 行.get(甲, {}).get("门店") == "SH001" and 行.get("U001", {}).get("门店") is None, {k: v.get("门店") for k, v in 行.items() if k in (甲, 乙, "U001")})
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"摘要": "扣子掉了", "门店": "SH001"}})
    rid2 = (r or {}).get("resource_id")
    st = 等到(rid2, ("waiting_approval", "failed", "succeeded", "cancelled")) if rid2 else None
    with 事务() as cx:
        行2 = cx.execute(text("select id, store_id, target_ref from human_requests where project_id=:p and execution_run_id=:r order by created_at desc limit 1"), {"p": 项目, "r": rid2}).mappings().first()
    hid2 = 行2["id"] if 行2 else None
    tr = 行2["target_ref"] if 行2 else {}
    if isinstance(tr, str):
        tr = json.loads(tr)
    ck("输入带 门店=SH001 → 挂起的待办 store_id=SH001,target_ref 记来源「运行的输入」", c == 202 and st == "waiting_approval" and 行2 and 行2["store_id"] == "SH001" and (tr or {}).get("门店来源") == "运行的输入", (c, st, dict(行2) if 行2 else None))
    c, L = 打("GET", P + "/human-requests?limit=200")
    ids = [x["id"] for x in (L or {}).get("items") or []]
    ck("U001 没登记门店 → 看全部:新单(SH001)和旧单(定不出门店)都在,行上带「门店」", hid2 in ids and hid in ids and any(x["id"] == hid2 and x.get("门店") == "SH001" for x in L["items"]) and (L or {}).get("我的门店") is None, (c, len(ids)))
    c, L = 打("GET", P + "/human-requests?limit=200", 谁=乙)
    ids乙 = [x["id"] for x in (L or {}).get("items") or []]
    ck("SH002 的店长:列表里没有 SH001 的单子、也没有定不出门店的旧单;note 写了只列本店", c == 200 and hid2 not in ids乙 and hid not in ids乙 and (L or {}).get("我的门店") == "SH002" and all(x.get("门店") == "SH002" for x in L["items"]), (c, ids乙[:3], (L or {}).get("我的门店")))
    c, b = 打("GET", P + f"/human-requests/{hid2}", 谁=乙)
    ck("SH002 的店长开 SH001 的单子 → 404(不说「有这单但不是你的」)", c == 404 and 码(b) == "NOT_FOUND", (c, b))
    c, b = 打("POST", P + f"/human-requests/{hid2}/decisions", 谁=乙, 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"decision": "门店责任", "request_revision": 1, "edits": {"赔付": "退款"}})
    ck("SH002 的店长对它做决定 → 404,没记进去", c == 404, (c, b))
    c, b = 打("GET", P + f"/human-requests/{hid}", 谁=甲)
    ck("SH001 的店长开定不出门店的旧单 → 404(那种只给不限门店的人)", c == 404, (c, b))
    c, L = 打("GET", P + "/human-requests?limit=200&mine=true", 谁=甲)
    ids甲 = [x["id"] for x in (L or {}).get("items") or []]
    ck("SH001 的店长「只看我能处理的」:有这张新单,列出来的每条「还能处理吗」都是真", c == 200 and hid2 in ids甲 and all(x.get("还能处理吗") for x in L["items"]) and (L or {}).get("只看我能处理的") is True, (c, ids甲[:3]))
    c, 详 = 打("GET", P + f"/human-requests/{hid2}", 谁=甲)
    ck("SH001 的店长开详情:门店 SH001、来源「运行的输入」、你能处理吗 = 真", c == 200 and (详 or {}).get("门店") == "SH001" and (详 or {}).get("门店来源") == "运行的输入" and (详 or {}).get("你能处理吗") is True, (c, {k: (详 or {}).get(k) for k in ("门店", "门店来源", "你能处理吗", "为什么")}))
    rev2 = ((详 or {}).get("请求") or {}).get("revision") or 1
    c, b = 打("POST", P + f"/human-requests/{hid2}/decisions", 谁=甲, 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"decision": "顾客责任", "request_revision": rev2, "edits": {"赔付": "换货"}})
    ck("SH001 的店长做决定 → 201,处理人记的是他", c == 201 and (b or {}).get("处理人") == 甲, (c, b))
    c, b = 打("POST", P + "/memberships", 体={"工号": 甲, "角色": "admin", "门店": ""})
    c3, m = 打("GET", P + "/memberships")
    ck("门店传空串 → 清成不限门店", c == 201 and (b or {}).get("门店") is None and next((x for x in (m or {}).get("成员") or [] if x["工号"] == 甲), {}).get("门店") is None, (c, b))
    c, b = 打("POST", P + "/memberships", 体={"工号": 甲, "角色": "admin", "门店": "静安 店"})
    ck("门店编号写成中文 / 带空格 → 422 说只收字母数字", c == 422, (c, b))

    print("\n▸ ⑦ 到期走「超时」出口(11-21 用户拍,照 Dify):接了线,到期不失败、从那条线接着走")
    c, w2 = 打("POST", P + "/workflows", 体={"名称": f"e2e 人工超时 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid2 = (w2 or {}).get("id")
    建的.append(wid2)
    c, d2 = 打("GET", P + f"/workflows/{wid2}")
    定义2 = json.loads(json.dumps(定义, ensure_ascii=False))
    核 = next(n for n in 定义2["nodes"] if n["id"] == "核")
    核["config"]["expires_at_policy"] = {"小时": 0.0004, "到期": "fail"}   # 约 1.4 秒就到期
    定义2["nodes"].append(模板("超路", "超时:"))
    next(n for n in 定义2["nodes"] if n["id"] == "汇")["config"]["candidates"].append({"source": "node", "node_id": "超路", "pointer": "/文本"})
    定义2["edges"] += [{"source": "核", "target": "超路", "port": "timeout"}, {"source": "超路", "target": "汇", "port": "success"}]
    c, b = 打("PATCH", P + f"/workflows/{wid2}/draft", 体={"定义": 定义2}, 头={"If-Match": str(d2["草稿"]["revision"])})
    c2, vb = 打("POST", P + f"/workflows/{wid2}/validate")
    阻 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("带「超时」线的草稿存得了、检查配置无阻断(超时是登记过的端口)", c == 200 and c2 == 200 and 阻 == [], (c, b, c2, 阻))
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid2, "输入": {"摘要": "没人管", "门店": "SH001"}})
    rid3 = (r or {}).get("resource_id")
    st = 等到(rid3, ("waiting_approval", "failed", "succeeded", "cancelled")) if rid3 else None
    ck("先停在等人核对", c == 202 and st == "waiting_approval", (c, st))
    time.sleep(2.0)   # 过了截止时间;worker 每轮先 扫过期核对(待办记 expired + 排恢复),再处理恢复任务
    st = 等到(rid3, ("succeeded", "failed", "cancelled", "expired"), 最多=12)
    with 事务() as cx:
        行3 = cx.execute(text("select output_ref from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid3}).mappings().first()
        待3 = cx.execute(text("select status from human_requests where project_id=:p and execution_run_id=:r order by created_at desc limit 1"), {"p": 项目, "r": rid3}).scalar()
        步3 = cx.execute(text("select node_id, status, branch_key from run_steps where project_id=:p and execution_run_id=:r order by created_at"), {"p": 项目, "r": rid3}).mappings().all()
        事3 = [x[0] for x in cx.execute(text("select event_type from run_events where project_id=:p and execution_run_id=:r order by seq"), {"p": 项目, "r": rid3}).all()]
    出3 = (行3 or {}).get("output_ref") or {}
    if isinstance(出3, str):
        出3 = json.loads(出3)
    ck("到期后运行**没失败**,从「超时」口接着走到结束,输出 超时:__timeout__;待办记「已过期」;事件里有 human.timeout",
       st == "succeeded" and 出3.get("text") == "超时:__timeout__" and 待3 == "expired" and "human.timeout" in 事3
       and any(x["node_id"] == "核" and x["branch_key"] == "__timeout__" for x in 步3), (st, 出3, 待3, 事3, [dict(x) for x in 步3]))
    c, L = 打("GET", P + "/human-requests?limit=200&status=expired")
    ck("过期的待办在列表里能按 status=expired 筛到,「还能处理吗」为否", c == 200 and any(x["execution_run_id"] == rid3 and not x.get("还能处理吗") for x in (L or {}).get("items") or []), (c, len((L or {}).get("items") or [])))

    print("\n▸ ⑧ 收尾")
    收尾()
    ck("工作流已归档", True)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ 人工介入表单化 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
