#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 请求节点 · 端到端(三期 3-1,11-16)—— **一个真请求都不发**:受理成 mock 的运行,worker 的 _http 交替身。

验的是接线,不是判据(判据在 tests/orchestration/test_outbound_policy.py / test_http_node.py):
  ① 登记一条工具连接(白名单 + 凭据引用)→ 201,返回里密钥只给形状
  ② 空白模板建图:开始 → HTTP 请求(选这条连接、GET、/stock)→ 结束(把实际地址和执行模式交出去)→ 检查配置无阻断
  ③ 检查配置在**进程内**也核一遍(咬合打得到):POST → HTTP_METHOD_NOT_ALLOWED;没路径 → HTTP_PATH_MISSING;连接不在 → REF_NOT_FOUND
  ④ 受理 → worker 跑成:结束节点交出的地址 = 白名单第一项 + 路径 + 查询串,执行模式 mock(一个字节都没出去);步骤记录里 h 这一步 succeeded
  ⑤ 收尾:连接归档、工作流归档(不留夹具)
⚠️ 常驻 worker 会和测试自己起的 worker 抢活 —— 两边跑的都是 _http 的 mock 支,结果一样;但副本里改坏 worker.py 打不准,
   所以这份的咬合规格打在**进程内**的 validator 上(③)。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import validator as V  # noqa: E402

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
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"], capture_output=True, text=True, timeout=180, cwd=根,
                   env=dict(os.environ, MODEL_ADAPTER="mock"))


def 状态(rid):
    with 事务() as c:
        return c.execute(text("select status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()


def 等到(rid, 要的, 最多=10):
    for _ in range(最多):
        s = 状态(rid)
        if s in 要的:
            return s
        跑worker()
        time.sleep(0.3)
    return 状态(rid)


白名单 = ["https://api.e2e-http.test/v1"]
print("▸ ① 登记一条工具连接")
# 登记连接走「配置密钥与预算」权限,U002(编辑)没有 → 403;用管理员 U001 建。图和运行照旧用 U002(编辑者日常就是这么用的)。
c, b = 打("POST", P + "/capability-connections", "U001", 体={"名字": f"e2e HTTP 连接 {uuid.uuid4().hex[:6]}", "适配器": "http",
                                                            "允许的端点": 白名单, "secret_ref": "env://E2E_HTTP_KEY_不存在也行"})
cid = (b or {}).get("id")  # 登记接口回的是 id(不是 connection_id)—— 11-16 首跑猜错过一次
ck("建连接 → 201,返回里密钥只给形状、不回显引用", c == 201 and cid and "E2E_HTTP_KEY" not in json.dumps(b, ensure_ascii=False), (c, b))

print("\n▸ ② 空白模板建图:开始 → HTTP 请求 → 结束")
出 = {"type": "object", "required": ["地址", "模式"], "properties": {"地址": {"type": "string"}, "模式": {"type": "string"}}, "additionalProperties": False}
入 = {"type": "object", "properties": {}, "additionalProperties": False}


def 图(定义, *, method="GET", path="/stock", connection_id=None):
    cfg = {"connection_id": connection_id or cid, "method": method, "query": {"sku": "A1"},
           "output_schema": {"type": "object", "required": ["status_code", "url", "execution_mode"],
                             "properties": {"status_code": {"type": "integer"}, "url": {"type": "string"}, "execution_mode": {"type": "string"}},
                             "additionalProperties": True}}
    if path is not None:
        cfg["path"] = path
    return dict(定义, input_schema=入, output_schema=出,
                nodes=[{"id": "start", "type": "start", "config": {"input_schema": 入}, "layout": {"x": 40, "y": 120}},
                       {"id": "h", "type": "http_request", "config": cfg, "layout": {"x": 330, "y": 120}},
                       {"id": "finish", "type": "end", "config": {"output_schema": 出, "bindings": {
                           "地址": {"source": "node", "node_id": "h", "pointer": "/url"},
                           "模式": {"source": "node", "node_id": "h", "pointer": "/execution_mode"}}}, "layout": {"x": 620, "y": 120}}],
                edges=[{"port": "success", "source": "start", "target": "h"}, {"port": "success", "source": "h", "target": "finish"}])


c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e HTTP 节点 {uuid.uuid4().hex[:6]}", "模板": "空白"})
wid = w["id"]
c, d = 打("GET", P + f"/workflows/{wid}")
定义 = 图(d["草稿"]["定义"])
c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
阻 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
ck("存草稿 200 · 检查配置无阻断(连接在、GET、路径写了)", c == 200 and c2 == 200 and 阻 == [], (c, b, c2, 阻))

print("\n▸ ③ 检查配置在进程内也核一遍(方法 / 路径 / 连接)")


def 阻断码(g, 在=True):
    ps = V.校验(g, 依赖存在=lambda 种类, i: 在)
    return sorted({p.get("code") for p in ps if p.get("级别") == V.阻断})


ck("GET → 无阻断", 阻断码(图(d["草稿"]["定义"])) == [], 阻断码(图(d["草稿"]["定义"])))
ck("POST → 检查配置拦 HTTP_METHOD_NOT_ALLOWED(一期只开读,H6)", 阻断码(图(d["草稿"]["定义"], method="POST")) == ["HTTP_METHOD_NOT_ALLOWED"],
   阻断码(图(d["草稿"]["定义"], method="POST")))
ck("没写路径 → 检查配置拦 HTTP_PATH_MISSING", "HTTP_PATH_MISSING" in 阻断码(图(d["草稿"]["定义"], path=None)), 阻断码(图(d["草稿"]["定义"], path=None)))
ck("连接不在(被删 / 不在本项目)→ REF_NOT_FOUND", 阻断码(图(d["草稿"]["定义"], connection_id="cc_不存在"), 在=False) == ["REF_NOT_FOUND"],
   阻断码(图(d["草稿"]["定义"], connection_id="cc_不存在"), 在=False))

print("\n▸ ④ 受理 → worker 跑成(mock:一个字节都没出去)")
c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {}})
rid = (r or {}).get("resource_id")
ck("受理 202,拿到运行号", c == 202 and rid, (c, r))
st = 等到(rid, ("succeeded", "failed", "cancelled")) if rid else None
with 事务() as cx:
    行 = cx.execute(text("select output_ref, execution_mode from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).mappings().first() if rid else None
    步 = cx.execute(text("select node_id, status, error_code from run_steps where project_id=:p and execution_run_id=:i order by created_at"),
                    {"p": 项目, "i": rid}).mappings().all() if rid else []
出了 = (行 or {}).get("output_ref") or {}
if isinstance(出了, str):  # 库里存的是 JSON 文本(worker 自己也是 json.loads 回来用)
    try:
        出了 = json.loads(出了)
    except Exception:
        出了 = {"_原文": 出了}
ck("跑成 succeeded;结束节点交出的地址 = 白名单第一项 + 路径 + 查询串", st == "succeeded" and 出了.get("地址") == "https://api.e2e-http.test/v1/stock?sku=A1",
   (st, 出了, [dict(x) for x in 步]))
ck("执行模式 mock(受理成 mock,HTTP 那一步交的是替身)", 出了.get("模式") == "mock" and (行 or {}).get("execution_mode") == "mock", (出了, dict(行 or {})))
ck("步骤记录里 h 这一步 succeeded、没有错误码", any(x["node_id"] == "h" and x["status"] == "succeeded" and not x["error_code"] for x in 步), [dict(x) for x in 步])

print("\n▸ ⑤ 收尾")
c1, _ = 打("DELETE", P + f"/workflows/{wid}", "U001")
c2, _ = 打("DELETE", P + f"/capability-connections/{cid}", "U001")
with 事务() as cx:
    cx.execute(text("update capability_connections set archived_at=coalesce(archived_at, now()) where project_id=:p and id=:i"), {"p": 项目, "i": cid})
    cx.execute(text("update workflows set archived_at=coalesce(archived_at, now()) where project_id=:p and id=:i"), {"p": 项目, "i": wid})
print(f"  连接 / 工作流已归档(接口 {c1} / {c2},库里兜底)")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ HTTP 请求节点:' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
