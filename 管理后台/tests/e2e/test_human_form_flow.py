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
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": {"type": "object", "properties": {"摘要": {"type": "string"}}, "required": ["摘要"]}}},
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
        hid = cx.execute(text("select id from human_requests where project_id=:p and execution_run_id=:r order by created_at desc limit 1"), {"p": 项目, "i": rid, "r": rid}).scalar()
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

    print("\n▸ ⑥ 收尾")
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
