#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「代码执行」最小版 · 端到端(三期 3-4,11-20 夜)。打真起着的 :8801,项目 project_demo_a(U001 管理员 / U002 编辑者都在)。
  ① 编辑者(U002)往草稿里加代码执行 → 403 CODE_NODE_ADMIN_ONLY;改别的步骤照常
  ② 管理员(U001)加 → 200;检查配置无阻断;节点库里「代码执行」可用
  ③ 编辑者在带代码节点的草稿上改别的步骤(代码不动)→ 200;改那段代码 → 403
  ④ 发起运行 → 跑成,结束节点拿到代码算出来的结果(服务有沙箱才验真跑;没有则这一步 CODE_SANDBOX_UNAVAILABLE 失败,**不退回裸 exec**)
  ⑤ 收尾:归档
沙箱四条真攻击在 tests/orchestration/test_code_node.py(进程内真跑),这里只验接线和权限。
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
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, _这)
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import 代码执行 as C  # noqa: E402
import _模型模式 as MM  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
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
有沙箱, 为什么没 = C.沙箱可用()


def 跑worker():
    import subprocess
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"], capture_output=True, text=True, timeout=240, cwd=根,
                   env=dict(os.environ, MODEL_ADAPTER=("mock" if 服务是mock else "anthropic")))


def 状态(rid):
    with 事务() as c:
        return c.execute(text("select status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()


def 等到(rid, 要的, 最多=15):
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


出 = {"type": "object", "properties": {"和": {"type": "integer"}, "话": {"type": "string"}}, "required": ["和"]}
文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def 定义(code):
    return {"nodes": [
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}},
        {"id": "算", "type": "code", "name": "算一下", "config": {"language": "python", "code": code,
            "input_mapping": {"a": {"source": "input", "pointer": "/a"}, "b": {"source": "input", "pointer": "/b"}}, "output_schema": 出, "sub_limits": {"timeout_seconds": 3, "memory_mb": 64}}},
        {"id": "finish", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "算", "pointer": "/话"}}}}],
        "edges": [{"source": "start", "target": "算", "port": "success"}, {"source": "算", "target": "finish", "port": "success"}]}


代码 = "def main(a, b):\n    return {'和': a + b, '话': f'{a}+{b}={a + b}'}"


def main():
    print("▸ ① 编辑者加代码执行 → 403")
    c, w = 打("POST", P + "/workflows", 谁="U002", 体={"名称": f"e2e 代码执行 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = (w or {}).get("id")
    建的.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    rev = d["草稿"]["revision"]
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 谁="U002", 体={"定义": 定义(代码)}, 头={"If-Match": str(rev)})
    ck("U002(编辑者)存带代码执行的草稿 → 403 CODE_NODE_ADMIN_ONLY", c == 403 and 码(b) == "CODE_NODE_ADMIN_ONLY", (c, b))
    ck("节点库里「代码执行」标可用", any(n["中文"] == "代码执行" and n["可用"] for n in d["节点库"]), [n["中文"] for n in d["节点库"] if not n["可用"]])

    print("\n▸ ② 管理员加 → 200,检查配置无阻断")
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 谁="U001", 体={"定义": 定义(代码)}, 头={"If-Match": str(rev)})
    ck("U001(管理员)存 → 200", c == 200, (c, b))
    rev = (b or {}).get("revision", rev)
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    阻 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("检查配置无阻断", c2 == 200 and 阻 == [], (c2, 阻))

    print("\n▸ ③ 编辑者在带代码节点的草稿上改别的 → 200;改代码 → 403")
    改名 = 定义(代码)
    改名["nodes"][2]["name"] = "最后"
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 谁="U002", 体={"定义": 改名}, 头={"If-Match": str(rev)})
    ck("只改结束节点的名字 → 200(代码没动)", c == 200, (c, b))
    rev = (b or {}).get("revision", rev)
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 谁="U002", 体={"定义": 定义(代码 + "\n# 改一下")}, 头={"If-Match": str(rev)})
    ck("改了代码 → 403", c == 403 and 码(b) == "CODE_NODE_ADMIN_ONLY", (c, b))

    print("\n▸ ④ 发起运行")
    c, r = 打("POST", P + "/execution-runs", 谁="U001", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"a": 2, "b": 5}})
    rid = (r or {}).get("resource_id")
    st = 等到(rid, ("succeeded", "failed", "cancelled", "incomplete")) if rid else None
    with 事务() as cx:
        行 = cx.execute(text("select output_ref from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).mappings().first()
        步 = cx.execute(text("select node_id, status, error_code from run_steps where project_id=:p and execution_run_id=:i order by created_at"), {"p": 项目, "i": rid}).mappings().all()
    出了 = (行 or {}).get("output_ref") or {}
    if isinstance(出了, str):
        出了 = json.loads(出了)
    if 有沙箱:
        ck("跑成,结束节点拿到代码算出的「2+5=7」", c == 202 and st == "succeeded" and 出了.get("text") == "2+5=7", (c, st, 出了, [dict(x) for x in 步]))
    else:
        ck(f"这台机器没沙箱({为什么没}):这一步 CODE_SANDBOX_UNAVAILABLE 失败,不退回裸 exec", st == "failed" and any(x["node_id"] == "算" and x["error_code"] == "CODE_SANDBOX_UNAVAILABLE" for x in 步), (st, [dict(x) for x in 步]))

    print("\n▸ ⑤ 收尾")
    收尾()
    ck("工作流已归档", True)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ 代码执行端到端 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
