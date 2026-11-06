#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流里的 Agent 步骤(2026-11-06;用户拍「现在就把执行器做出来」)—— 真跑 + 走澜绣桥 + 断点续跑,整条工作流跟着挂起 / 恢复。

前半段的说明照 test_agent_bridge_flow(本地假 Anthropic 接口、受理后把这一次改成 live 的理由一样)。这一份验的是**工作流那一层**:
  ① 受理时依赖指纹里**有 Agent 版本钉的那条连接**(Agent 的连接在 Agent 版本上,不在这一步的配置里)
  ② worker 真跑到 Agent 步骤:Agent 调「召回名单」→ **整条工作流**挂起,桥请求记在这一步名下(node_id = Agent 步骤)、参数是中文键
  ③ 回执 → 排回 workflow_run
  ④ 恢复:Agent 从它自己的检查点接着跑(不是把回执当这一步的输出)、交卷 → 工作流 succeeded,结束节点的输出就是 Agent 交的结果
  ⑤ 父流程的用量里算进了 Agent 这两回合(子任务消耗计入父任务额度,§6.1)
  ⑥ 真跑的回合进了用量账
  ⑦ allowed_capabilities 收窄到没有工具 → Agent 一个桥请求都不发(有效权限取交集)
  ⑧ 请求合法:工具名 / 参数名只用 ASCII

咬合打得到哪里:受理和回执在测试进程里调(TestClient,workflows_api / run_resume 在视野里);worker 那一段有常驻 worker 一起抢活,
副本里改坏打不准 —— 执行器那一层的咬合在 tests/orchestration/test_agent_step_runner.py;worker `_agent` 里上限 / 工具取交集**没有咬合**(已知限定)。

(以下是从 test_agent_bridge_flow 照搬的说明,保留着方便对照)

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


模式 = {"值": "mock"}      # 这次运行受理时定的模式 —— 测试起的 worker 跟着它设 MODEL_ADAPTER


def 跑worker():
    # 跟着受理时定的模式起 worker(11-06):工作流 worker 对「受理成 live、自己却只跑 mock」会拒跑(RUN_MODE_MISMATCH,
    # 那是对的 —— 不拿 mock 答案冒充真跑)。测试起的 worker 默认是 mock,不跟着设就会把 live 运行判失败
    import subprocess
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"], capture_output=True, text=True, timeout=180, cwd=根,
                   env=dict(os.environ, MODEL_ADAPTER="anthropic" if 模式["值"] == "live" else "mock"))


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


def 建Agent(cv, tv):
    c_, a = 打("POST", P + "/agents", 体={"名称": f"e2e 工作流里的 Agent {uuid.uuid4().hex[:6]}"})
    aid = a["id"]
    c_, d = 打("GET", P + f"/agents/{aid}")
    cfg = dict(d["草稿"]["配置"], connection_version_id=cv, tools=[tv],
               input_schema={"type": "object", "properties": {"顾问": {"type": "string"}}, "required": ["顾问"]},
               output_schema={"type": "object", "properties": {"名单": {"type": "array", "items": {"type": "string"}}},
                              "required": ["名单"]}, completion_criteria={})
    打("PATCH", P + f"/agents/{aid}/draft", 体={"配置": cfg}, 头={"If-Match": str(d["草稿"]["revision"])})
    c_, v = 打("POST", P + f"/agents/{aid}/versions", 体={"变更说明": "e2e 工作流 Agent 步骤"})
    return (v or {}).get("id") or (v or {}).get("版本id"), (c_, v)


def 建工作流(avid, 允许=None):
    c_, w = 打("POST", P + "/workflows", 体={"名称": f"e2e Agent 步骤 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = w["id"]
    c_, d = 打("GET", P + f"/workflows/{wid}")
    入 = {"type": "object", "required": ["顾问"], "properties": {"顾问": {"type": "string", "minLength": 1}}, "additionalProperties": False}
    出 = {"type": "object", "required": ["名单"], "properties": {"名单": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}
    a1 = {"id": "a1", "type": "agent", "config": {
        "agent_version_id": avid, "task_binding": "列出该回访的客户号",
        "input_mapping": {"顾问": {"source": "input", "pointer": "/顾问"}},
        "sub_limits": {"max_model_turns": 4, "max_tool_attempts": 3},
        **({"allowed_capabilities": 允许} if 允许 is not None else {})}, "layout": {"x": 330, "y": 120}}
    定义 = dict(d["草稿"]["定义"], input_schema=入, output_schema=出,
              nodes=[{"id": "start", "type": "start", "config": {"input_schema": 入}, "layout": {"x": 40, "y": 120}}, a1,
                     {"id": "finish", "type": "end", "config": {"bindings": {"名单": {"source": "node", "node_id": "a1", "pointer": "/名单"}},
                                                               "output_schema": 出}, "layout": {"x": 620, "y": 120}}],
              edges=[{"port": "success", "source": "start", "target": "a1"}, {"port": "success", "source": "a1", "target": "finish"}])
    c_, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    return wid, (c_, b, c2, [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"])


def 跑(wid):
    # 受理在**测试进程里**调(TestClient):咬合改坏 workflows_api 里受理那段(比如不算 Agent 版本的连接)时在视野里
    from fastapi.testclient import TestClient
    import main as _M
    _r = TestClient(_M.app).post(P + "/execution-runs", headers={"X-Dev-User": "U002", "Idempotency-Key": str(uuid.uuid4())},
                                 json={"workflow_id": wid, "输入": {"顾问": "林岚"}})
    c_, r = _r.status_code, (_r.json() if _r.content else None)
    rid = (r or {}).get("resource_id")
    if rid:
        with 事务() as c:
            模式["值"] = c.execute(text("select execution_mode from execution_runs where project_id=:p and id=:i"),
                                 {"p": 项目, "i": rid}).scalar()
    return rid, (c_, r)


def main():
    服务 = ThreadingHTTPServer(("127.0.0.1", 0), 假接口)
    threading.Thread(target=服务.serve_forever, daemon=True).start()
    端口 = 服务.server_address[1]
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
        c.execute(text("""insert into connection_versions (id, organization_id, project_id, connection_id, endpoint, secret_ref,
                              capabilities, created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, :m, :e, 'env://HOME', cast(:cap as jsonb), now(), 'e2e', now(), 1)"""),
                  {"i": cv, "o": org, "p": 项目, "m": mc, "e": f"http://127.0.0.1:{端口}/v1/messages",
                   "cap": json.dumps({"execution_mode": "live", "原生工具调用": True, "探法": "e2e 本地假接口"}, ensure_ascii=False)})
    avid, 建 = 建Agent(cv, tv)
    ck("前提:Agent 版本冻好了(钉假接口连接 + 只给「召回名单」)", bool(avid and tv), 建)
    wid, 建 = 建工作流(avid)
    ck("前提:开始 → Agent 步骤 → 结束 的工作流校验通过", 建[0] == 200 and not 建[3], 建)
    rid, 受 = 跑(wid)
    ck("前提:受理 202", 受[0] == 202, 受)
    if not rid:
        return 1
    真 = 模式["值"] == "live"
    print(f"  ℹ️ 这一次受理成 {模式['值']}(跟着部署的 MODEL_ADAPTER 走:CI / e2e 起的服务是 mock,本机常驻服务是真模型)——"
          f"{'这一轮连真模型那一支(本地假接口)一起验' if 真 else '这一轮验 mock 那一支;真模型那一支在本机常驻服务上验'}")
    with 事务() as c:
        fp = c.execute(text("select definition_ref->'依赖指纹' from execution_runs where project_id=:p and id=:i"),
                       {"p": 项目, "i": rid}).scalar() or {}
    ck("① 受理时依赖指纹里有 Agent 版本钉的那条连接(新算法)", str(fp.get(cv) or "").startswith("v2:"), fp)

    s = 等到(rid, ("waiting_external", "succeeded", "failed", "incomplete"))
    with 事务() as c:
        bc = c.execute(text("""select id, tool_name, arguments_snapshot, status, node_id from bridge_calls
                                where project_id=:p and execution_run_id=:r order by created_at"""),
                       {"p": 项目, "r": rid}).mappings().all()
        er = c.execute(text("select completion_reason from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()
    ck("② 跑到 Agent 步骤 → 整条工作流挂起,桥请求记在这一步名下(a1)、中文工具名、中文参数键「上限」",
       s == "waiting_external" and len(bc) == 1 and bc[0]["node_id"] == "a1" and bc[0]["tool_name"] == "召回名单"
       and bc[0]["arguments_snapshot"] == ({"上限": 5} if 真 else {}), (s, er, [dict(x) for x in bc]))
    if not bc:
        return 1
    from fastapi.testclient import TestClient
    import main as _M
    _r = TestClient(_M.app).post(P + f"/bridge-calls/{bc[0]['id']}/ack", headers={"X-Dev-User": "U002"},
                                 json={"结果": "已执行", "输出": {"客户": ["IT-C901"]}})
    ak = _r.json() if _r.content else {}
    with 事务() as c:
        jt = c.execute(text("select type from jobs where project_id=:p and id=:j"), {"p": 项目, "j": ak.get("恢复任务")}).scalar()
    ck("③ 回执 → 排回 workflow_run", _r.status_code == 200 and jt == "workflow_run", (_r.status_code, ak, jt))

    s = 等到(rid, ("succeeded", "failed", "incomplete"))
    第二次 = 请求们[1] if len(请求们) > 1 else {}
    回执里 = json.dumps([b for m in 第二次.get("messages") or [] if m["role"] == "user"
                       for b in (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "tool_result"],
                      ensure_ascii=False)
    with 事务() as c:
        行 = c.execute(text("select output_ref, usage_snapshot, completion_reason from execution_runs where project_id=:p and id=:i"),
                      {"p": 项目, "i": rid}).mappings().first()
        账 = list(c.execute(text("select source, quantity from usage_ledger where project_id=:p and event_key like :k"),
                           {"p": 项目, "k": f"{rid}:a1:%"}).mappings())
    出 = 行["output_ref"]
    出 = json.loads(出) if isinstance(出, str) else 出
    with 事务() as c:
        类 = list(c.execute(text("select event_type from run_events where project_id=:p and execution_run_id=:r order by seq"),
                           {"p": 项目, "r": rid}).scalars())
    接着 = ("agent.resumed" in 类 and "tool.receipt_applied" in 类 and "agent.finish_claimed" in 类
            and 类.index("run.suspended") < 类.index("agent.resumed") < 类.index("agent.finish_claimed")) if "run.suspended" in 类 else False
    ck("④ 恢复:Agent 从它自己的检查点接着跑(resumed → 回执 → 交卷)→ 工作流 succeeded,结束节点输出 = Agent 交的结果",
       s == "succeeded" and 接着 and (出 or {}).get("名单") == (["IT-客户1"] if 真 else [])
       and (not 真 or (len(请求们) == 2 and "IT-C901" in 回执里)), (s, 行["completion_reason"], 出, 类[-8:]))
    用 = 行["usage_snapshot"]
    用 = json.loads(用) if isinstance(用, str) else (用 or {})
    ck("⑤ 父流程的用量里算进了 Agent 这两回合(子任务消耗计入父任务额度)", int(用.get("模型调用") or 0) == 2, 用)
    ck("⑥ 用量账:真跑的回合全进账(live,合计 2 × (111 + 22));mock 一笔都不记(没花钱)",
       (账 and all(x["source"] == "live" for x in 账) and sum(int(x["quantity"]) for x in 账) == 266) if 真 else not 账,
       [dict(x) for x in 账])

    # ⑦
    请求们.clear()
    wid2, 建2 = 建工作流(avid, 允许=["tv_不存在的工具"])
    rid2, _ = 跑(wid2)
    s2 = 等到(rid2, ("waiting_external", "succeeded", "failed", "incomplete"))
    with 事务() as c:
        n桥 = c.execute(text("select count(*) from bridge_calls where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": rid2}).scalar()
    给的工具 = [t["name"] for t in (请求们[0].get("tools") if 请求们 else [])]
    ck("⑦ allowed_capabilities 收窄到没有工具 → 模型拿不到「召回名单」、一个桥请求都不发",
       s2 == "succeeded" and n桥 == 0 and not any(re.fullmatch(r"t\d+", x) for x in 给的工具), (s2, n桥, 给的工具))
    if not 真:
        print("  ℹ️ ⑧ mock 这一轮没发模型请求 —— 请求合法那条只在真模型那一支验(**不是验过了**)")

    if 真:
        违规 = [t["name"] for 体 in 请求们 for t in 体.get("tools") or [] if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t["name"])]
        ck("⑧ 请求里的工具名只用 ASCII", not 违规, 违规)
    with 事务() as c:
        c.execute(text("update model_connections set status='archived', archived_at=now(), updated_at=now() where project_id=:p and id=:i"),
                  {"p": 项目, "i": mc})
    服务.shutdown()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 工作流里的 Agent 步骤:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
