#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 写工具当场审批(2026-11-06;用户拍:每次写都当场审批、店长批、24 小时作废、只能批或退回)—— 端到端。

本地假 Anthropic 接口 + 受理后把这一次改成 live(理由同 test_agent_bridge_flow)。工具用澜绣桥里「要批准」的「派补货跟进」。
  ① Agent 要写 → 运行停在 waiting_approval,记了一条人工待办:种类「Agent写操作审批」、审批人 approver / admin(店长)、
     **不许改**(allowed_fields 为空)、约 24 小时后截止、target_ref 里有这一次的参数摘要;还没有桥请求
  ② 店长打开待办看得到 Agent 要对什么做什么(工具、参数)
  ③ 店长批准(真接口)→ 排回 agent_run → 带着批准交给桥(**桥闸认了这条批准**,记了桥请求)→ 回执 → 交卷 succeeded
  ④ 另一次:店长退回并写理由 → Agent 收到「店长退回了」和理由(假接口的第二次请求里看得到)→ 一张桥请求都没有
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
PY = os.path.join(根, ".venv", "bin", "python")
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    h = {"X-Dev-User": 谁, "Content-Type": "application/json", **(头 or {})}
    rq = urllib.request.Request(基址 + 路, method=方法, headers=h,
                                data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 跑worker():
    import subprocess
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"],
                   capture_output=True, text=True, timeout=180, cwd=根)


def 状态(rid):
    with 事务() as c:
        return c.execute(text("select status from execution_runs where project_id=:p and id=:i"),
                         {"p": 项目, "i": rid}).scalar()


def 等到(rid, 要的, 最多=10):
    for _ in range(最多):
        s = 状态(rid)
        if s in 要的:
            return s
        跑worker()
        time.sleep(0.3)
    return 状态(rid)


# ── 本地假 Anthropic 接口 ─────────────────────────────────────────
请求们 = []


def _填(schema):
    """按 schema 现填一份合法参数(所有字段都填,好让参数名的往返被验到)。"""
    t = (schema or {}).get("type")
    if t == "object":
        return {k: _填(v) for k, v in ((schema or {}).get("properties") or {}).items()}
    if t == "array":
        return ["IT-客户1"]
    if t == "integer":
        return 5
    if t == "number":
        return 1.5
    if t == "boolean":
        return True
    return "IT-测试"


class 假接口(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        体 = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        请求们.append(体)
        有回执 = any(b.get("type") == "tool_result" for m in 体.get("messages") or [] if m["role"] == "user"
                  for b in (m["content"] if isinstance(m["content"], list) else []))
        工具们 = {t["name"]: t for t in 体.get("tools") or []}
        _t = [n for n in 工具们 if re.fullmatch(r"t\d+", n)]
        if not 有回执 and _t:
            名 = _t[0]
            块 = [{"type": "tool_use", "id": "toolu_e2e_1", "name": 名, "input": _填(工具们[名]["input_schema"])}]
        else:
            块 = [{"type": "tool_use", "id": "toolu_e2e_2", "name": "submit_result",
                  "input": _填(工具们["submit_result"]["input_schema"])}]
        出 = json.dumps({"id": f"msg_e2e_{len(请求们)}", "type": "message", "role": "assistant",
                        "model": "claude-haiku-4-5", "content": 块, "stop_reason": "tool_use",
                        "usage": {"input_tokens": 111, "output_tokens": 22}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(出)))
        self.end_headers()
        self.wfile.write(出)


def 准备(端口):
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        tv = c.execute(text("""select tv.id from tool_versions tv join tool_definitions td
                                 on td.project_id=tv.project_id and td.id=tv.tool_definition_id
                              where tv.project_id=:p and td.name='派补货跟进' and td.adapter='lanxiu_bridge'
                                and td.status='active' order by tv.created_at desc limit 1"""), {"p": 项目}).scalar()
        mc, cv = "mc_e2e_" + uuid.uuid4().hex[:8], "cv_e2e_" + uuid.uuid4().hex[:8]
        c.execute(text("""insert into model_connections (id, organization_id, project_id, purpose, adapter, display_name,
                              status, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, 'generate', 'anthropic-messages', 'e2e 本地假接口', 'active', now(), 'e2e', now(), 1)"""),
                  {"i": mc, "o": org, "p": 项目})
        c.execute(text("""insert into connection_versions (id, organization_id, project_id, connection_id, endpoint, secret_ref,
                              capabilities, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, :m, :e, 'env://HOME', cast(:cap as jsonb), now(), 'e2e', now(), 1)"""),
                  {"i": cv, "o": org, "p": 项目, "m": mc, "e": f"http://127.0.0.1:{端口}/v1/messages",
                   "cap": json.dumps({"execution_mode": "live", "原生工具调用": True}, ensure_ascii=False)})
    c_, a = 打("POST", P + "/agents", 体={"名称": f"e2e 写审批 Agent {uuid.uuid4().hex[:6]}"})
    aid = a["id"]
    c_, d = 打("GET", P + f"/agents/{aid}")
    cfg = dict(d["草稿"]["配置"], connection_version_id=cv, tools=[tv],
               input_schema={"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
               output_schema={"type": "object", "properties": {"结果": {"type": "string"}}, "required": ["结果"]},
               completion_criteria={})
    打("PATCH", P + f"/agents/{aid}/draft", 体={"配置": cfg}, 头={"If-Match": str(d["草稿"]["revision"])})
    c_, b = 打("POST", P + f"/agents/{aid}/validate")
    打("POST", P + f"/agents/{aid}/versions", 体={"变更说明": "e2e 写审批"})
    return aid, mc, tv, (c_, b.get("通过") if b else None, [p.get("code") for p in (b or {}).get("问题", []) if p.get("级别") == "blocking"])


def 跑一次(aid):
    c_, r = 打("POST", P + "/agent-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"agent_id": aid, "输入": {"sku": "IT-SKU1"}})
    rid = (r or {}).get("resource_id")
    if rid:
        with 事务() as c:
            c.execute(text("update execution_runs set execution_mode='live' where project_id=:p and id=:i"), {"p": 项目, "i": rid})
    return rid


def 待办(rid):
    with 事务() as c:
        return c.execute(text("""select id, kind, candidate_roles, allowed_fields, expires_at, target_ref, revision,
                                        extract(epoch from (expires_at - now()))/3600 as 剩小时
                                   from human_requests where project_id=:p and execution_run_id=:r order by created_at desc limit 1"""),
                         {"p": 项目, "r": rid}).mappings().first()


def 桥单数(rid):
    with 事务() as c:
        return c.execute(text("select count(*) from bridge_calls where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": rid}).scalar()


def 决定(hid, rev, 决, 理由):
    from fastapi.testclient import TestClient
    import main as _M
    r = TestClient(_M.app).post(P + f"/human-requests/{hid}/decisions", headers={"X-Dev-User": "U006", "Idempotency-Key": str(uuid.uuid4())},
                                json={"decision": 决, "request_revision": rev, "reason": 理由})
    return r.status_code, (r.json() if r.content else None)


def main():
    服务 = ThreadingHTTPServer(("127.0.0.1", 0), 假接口)
    threading.Thread(target=服务.serve_forever, daemon=True).start()
    aid, mc, tv, 校 = 准备(服务.server_address[1])
    ck("前提:演示项目里有「派补货跟进」桥工具,Agent 校验通过", bool(tv) and 校[1], 校)

    rid = 跑一次(aid)
    s = 等到(rid, ("waiting_approval", "waiting_external", "succeeded", "failed", "incomplete"))
    h = 待办(rid)
    tr = (h or {}).get("target_ref") or {}
    ck("① Agent 要写 → 停在 waiting_approval,记一条「Agent写操作审批」待办:店长(approver / admin)、不许改、约 24 小时截止、带参数摘要;还没有桥请求",
       s == "waiting_approval" and h and h["kind"] == "Agent写操作审批" and set(h["candidate_roles"]) == {"approver", "admin"}
       and h["allowed_fields"] == [] and 23 < float(h["剩小时"] or 0) <= 24 and tr.get("参数摘要") and 桥单数(rid) == 0,
       (s, dict(h) if h else None))
    if not h:
        return 1
    c_, dd = 打("GET", P + f"/human-requests/{h['id']}", 谁="U006")
    材 = json.dumps((dd or {}).get("核对材料") or {}, ensure_ascii=False)
    ck("② 店长打开待办看得到 Agent 要执行的工具和参数", c_ == 200 and "派补货跟进" in 材 and "IT-" in 材, (c_, 材[:200]))

    c_, dec = 决定(h["id"], h["revision"], "approved", "可以")
    s = 等到(rid, ("waiting_external", "succeeded", "failed", "incomplete", "waiting_approval"))
    with 事务() as c:
        bc = c.execute(text("select id, tool_name, status from bridge_calls where project_id=:p and execution_run_id=:r"),
                       {"p": 项目, "r": rid}).mappings().all()
        原因 = c.execute(text("select completion_reason from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()
    ck("③ 店长批准 → 接着跑 → 带着批准交给桥(桥闸认了这条批准,记了桥请求「派补货跟进」)",
       c_ == 201 and s == "waiting_external" and len(bc) == 1 and bc[0]["tool_name"] == "派补货跟进", (c_, dec, s, 原因, [dict(x) for x in bc]))
    if bc:
        from fastapi.testclient import TestClient
        import main as _M
        TestClient(_M.app).post(P + f"/bridge-calls/{bc[0]['id']}/ack", headers={"X-Dev-User": "U002"},
                                json={"结果": "已执行", "输出": {"跟进": "tk_e2e"}})
        s = 等到(rid, ("succeeded", "failed", "incomplete"))
        ck("③ 回执 → 交卷 succeeded", s == "succeeded", s)

    请求们.clear()
    rid2 = 跑一次(aid)
    s2 = 等到(rid2, ("waiting_approval", "succeeded", "failed", "incomplete"))
    h2 = 待办(rid2)
    c_, _ = 决定(h2["id"], h2["revision"], "rejected", "这个 SKU 下周才到货,先别派") if h2 else (None, None)
    s2 = 等到(rid2, ("succeeded", "failed", "incomplete", "waiting_external", "waiting_approval"))
    回执里 = json.dumps([b for 体 in 请求们[1:] for m in 体.get("messages") or [] if m["role"] == "user"
                       for b in (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "tool_result"],
                      ensure_ascii=False)
    ck("④ 店长退回并写理由 → Agent 收到「店长退回了」和理由 → 一张桥请求都没有",
       c_ == 201 and s2 == "succeeded" and "下周才到货" in 回执里 and "HUMAN_REJECTED" not in 回执里[:0] and 桥单数(rid2) == 0,
       (c_, s2, 回执里[:300], 桥单数(rid2)))

    with 事务() as c:
        c.execute(text("update model_connections set status='archived', archived_at=now(), updated_at=now() where project_id=:p and id=:i"),
                  {"p": 项目, "i": mc})
    服务.shutdown()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Agent 写工具当场审批:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
