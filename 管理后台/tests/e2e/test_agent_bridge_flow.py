#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台单独跑的 Agent 真跑 + 走澜绣桥 + 断点续跑(2026-11-06;用户拍「现在就把执行器做出来」「走桥」)。

**模型那一头是这个测试自己起的本地假 Anthropic 接口**(127.0.0.1,随机端口)—— CI 上没有模型凭据,
也不该真花钱;而受理之后的那一整条链全是真代码:worker 真跑 → 真模型.对话一轮(curl)→ 工具协议翻译 →
工具网关 → 交给桥(挂起、记桥请求、存检查点)→ 回执(真接口)→ run_resume 按 kind 排回 agent_run →
worker 从检查点接着跑 → 交卷 → 用量逐回合进账本。

  ① 受理之后 worker 真跑:第一回合模型用代号调「召回名单」→ 运行挂起(waiting_external),
     记了一张桥请求:工具是中文名、**参数是中文键「上限」**(代号在翻译层就还原了)、待执行
  ② 挂起时存了检查点、没有占着 worker(任务结束)、假接口只被问了 1 次
  ③ 回执(真接口)→ 排回恢复任务,而且**排给 agent_run**(原来写死 workflow_run)
  ④ 续跑:第二次请求里带着桥的回执(tool_result 里有回执的客户号)、模型交卷 → succeeded,输出就是交的那份
  ⑤ 事件链:run.suspended → agent.resumed → tool.receipt_applied → agent.finish_claimed
  ⑥ 真跑的两回合都进用量账(全是 live、合计是假接口回的 token 数)
  ⑦ 两次请求都合法:工具名 / 参数名只用 ASCII、tool_use 在下一条里都有回

咬合打得到哪里:回执走测试进程里的 TestClient(run_resume 在视野里);worker 那一段有常驻 worker 一起抢活,
副本里改坏 worker 打不准 —— 续跑逻辑本身的咬合在 tests/orchestration/test_agent_resume.py。

为什么受理之后要把这次运行改成 live:e2e 起的那套服务 MODEL_ADAPTER=mock(tools/dev.sh 的默认),
受理一律记成 mock —— 这正是受理那一道该做的事(部署明确选了只跑 mock)。这里要验的是 live 之后那一整条链,
所以在库里把**这一次**改成 live;受理那一道的口径另有单测(和工作流受理同一条规矩)。
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
        if not 有回执:
            名 = [n for n in 工具们 if n.startswith("t")][0]
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


def main():
    服务 = ThreadingHTTPServer(("127.0.0.1", 0), 假接口)
    threading.Thread(target=服务.serve_forever, daemon=True).start()
    端口 = 服务.server_address[1]
    print(f"▸ 本地假 Anthropic 接口:127.0.0.1:{端口}")

    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        tv = c.execute(text("""select tv.id from tool_versions tv join tool_definitions td
                                 on td.project_id=tv.project_id and td.id=tv.tool_definition_id
                              where tv.project_id=:p and td.name='召回名单' and td.adapter='lanxiu_bridge'
                                and td.status='active' order by tv.created_at desc limit 1"""), {"p": 项目}).scalar()
        mc, cv = "mc_e2e_" + uuid.uuid4().hex[:8], "cv_e2e_" + uuid.uuid4().hex[:8]
        c.execute(text("""insert into model_connections (id, organization_id, project_id, purpose, adapter, display_name,
                              status, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, 'generate', 'anthropic-messages', 'e2e 本地假接口', 'active', now(), 'e2e', now(), 1)"""),
                  {"i": mc, "o": org, "p": 项目})
        # 凭据用 env://HOME:常驻 worker 和测试起的 worker 都解析得出,而假接口不看它(请求只发到本机)
        c.execute(text("""insert into connection_versions (id, organization_id, project_id, connection_id, endpoint, secret_ref,
                              capabilities, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, :m, :e, 'env://HOME', cast(:cap as jsonb), now(), 'e2e', now(), 1)"""),
                  {"i": cv, "o": org, "p": 项目, "m": mc, "e": f"http://127.0.0.1:{端口}/v1/messages",
                   "cap": json.dumps({"execution_mode": "live", "原生工具调用": True, "探法": "e2e 本地假接口"},
                                     ensure_ascii=False)})
    ck("前提:演示项目里有澜绣桥的「召回名单」工具版本", bool(tv), tv)
    if not tv:
        return 1

    c_, a = 打("POST", P + "/agents", 体={"名称": f"e2e 走桥 Agent {uuid.uuid4().hex[:6]}"})
    aid = a["id"]
    c_, d = 打("GET", P + f"/agents/{aid}")
    cfg = dict(d["草稿"]["配置"], connection_version_id=cv, tools=[tv],
               input_schema={"type": "object", "properties": {"顾问": {"type": "string"}}, "required": ["顾问"]},
               output_schema={"type": "object", "properties": {"名单": {"type": "array", "items": {"type": "string"}}},
                              "required": ["名单"]},
               completion_criteria={})
    c_, b = 打("PATCH", P + f"/agents/{aid}/draft", 体={"配置": cfg}, 头={"If-Match": str(d["草稿"]["revision"])})
    c_, b = 打("POST", P + f"/agents/{aid}/validate")
    ck("前提:钉假接口连接 + 只给「召回名单」的 Agent 校验通过", c_ == 200 and b.get("通过"),
       [p.get("code") for p in (b or {}).get("问题", []) if p.get("级别") == "blocking"])
    c_, v = 打("POST", P + f"/agents/{aid}/versions", 体={"变更说明": "e2e 走桥"})
    c_, r = 打("POST", P + "/agent-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
              体={"agent_id": aid, "输入": {"顾问": "林岚"}})
    ck("前提:受理 202", c_ == 202, (c_, r))
    rid = r["resource_id"]
    with 事务() as c:
        c.execute(text("update execution_runs set execution_mode='live' where project_id=:p and id=:i"),
                  {"p": 项目, "i": rid})

    s = 等到(rid, ("waiting_external", "succeeded", "failed", "incomplete"))
    with 事务() as c:
        bc = c.execute(text("""select id, tool_name, arguments_snapshot, status, node_id from bridge_calls
                                where project_id=:p and execution_run_id=:r order by created_at"""),
                       {"p": 项目, "r": rid}).mappings().all()
        快 = c.execute(text("select resume_snapshot, completion_reason from execution_runs where project_id=:p and id=:i"),
                      {"p": 项目, "i": rid}).mappings().first()
    ck("① worker 真跑第一回合 → 挂起(waiting_external),记了一张桥请求:中文工具名、中文参数键「上限」、待执行",
       s == "waiting_external" and len(bc) == 1 and bc[0]["tool_name"] == "召回名单"
       and bc[0]["arguments_snapshot"] == {"上限": 5} and bc[0]["status"] == "待执行" and bc[0]["node_id"] == "agent",
       (s, [dict(x) for x in bc], (快 or {}).get("completion_reason")))
    ck("② 挂起时存了检查点(从 agent 接着)、假接口只被问了 1 次",
       (快["resume_snapshot"] or {}).get("从") == "agent" and (快["resume_snapshot"] or {}).get("检查点")
       and len(请求们) == 1, (len(请求们), list((快["resume_snapshot"] or {}).keys())))
    if not bc:
        return 1

    # 回执在**测试进程里**调接口(TestClient,用的是这份测试所在那一份代码):咬合在代码副本里改坏 run_resume 时,
    # 走 8801 的话服务端跑的是主检出那份、改动根本看不见 —— 「没红」就分不清是守住了还是没打到
    from fastapi.testclient import TestClient
    import main as _M
    _r = TestClient(_M.app).post(P + f"/bridge-calls/{bc[0]['id']}/ack", headers={"X-Dev-User": "U002"},
                                 json={"结果": "已执行", "输出": {"客户": ["IT-C900"]}})
    c_, ak = _r.status_code, (_r.json() if _r.content else None)
    with 事务() as c:
        jt = c.execute(text("select type from jobs where project_id=:p and id=:j"),
                       {"p": 项目, "j": (ak or {}).get("恢复任务")}).scalar()
    ck("③ 回执(真接口)→ 排回恢复任务,**排给 agent_run**(原来写死 workflow_run)",
       c_ == 200 and (ak or {}).get("恢复任务") and jt == "agent_run", (c_, ak, jt))

    s = 等到(rid, ("succeeded", "failed", "incomplete"))
    c_, ar = 打("GET", P + f"/execution-runs/{rid}", 谁="U004")
    第二次 = 请求们[1] if len(请求们) > 1 else {}
    回执里 = json.dumps([b for m in 第二次.get("messages") or [] if m["role"] == "user"
                       for b in (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "tool_result"],
                      ensure_ascii=False)
    with 事务() as c:
        出 = c.execute(text("select output_ref from execution_runs where project_id=:p and id=:i"),
                      {"p": 项目, "i": rid}).scalar()
        类 = list(c.execute(text("select event_type from run_events where project_id=:p and execution_run_id=:r order by seq"),
                           {"p": 项目, "r": rid}).scalars())
        账 = list(c.execute(text("""select source, quantity from usage_ledger
                                    where project_id=:p and event_key like :k order by created_at"""),
                           {"p": 项目, "k": f"{rid}:agent:%"}).mappings())
    ck("④ 续跑:第二次请求里带着桥的回执(IT-C900)、模型交卷 → succeeded,输出就是交的那份",
       s == "succeeded" and len(请求们) == 2 and "IT-C900" in 回执里
       and json.loads(出 or "null") == {"名单": ["IT-客户1"]}, (s, len(请求们), 回执里[:200], 出))
    要 = ["run.suspended", "agent.resumed", "tool.receipt_applied", "agent.finish_claimed"]
    位 = [类.index(k) if k in 类 else -1 for k in 要]
    ck("⑤ 事件链:run.suspended → agent.resumed → tool.receipt_applied → agent.finish_claimed",
       all(x >= 0 for x in 位) and 位 == sorted(位), 类)
    # 账本按输入 / 输出分开记(knowledge/usage.写进库 的口径),所以两回合是 4 行
    ck("⑥ 真跑的两回合都进了用量账:全是 live、合计 = 2 × (111 + 22)(假接口回的数)",
       len(账) >= 2 and all(x["source"] == "live" for x in 账) and sum(int(x["quantity"]) for x in 账) == 266,
       [dict(x) for x in 账])
    违规 = []
    for 体 in 请求们:
        for t in 体.get("tools") or []:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t["name"]):
                违规.append(t["name"])
            违规 += [k for k in ((t.get("input_schema") or {}).get("properties") or {})
                    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k)]
    ck("⑦ 两次请求的工具名 / 参数名都只用 ASCII(真接口只收这个)", not 违规 and 请求们, 违规)

    with 事务() as c:
        c.execute(text("""update model_connections set status='archived', archived_at=now(), updated_at=now()
                          where project_id=:p and id=:i"""), {"p": 项目, "i": mc})
    服务.shutdown()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Agent 真跑 + 走桥 + 断点续跑:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
