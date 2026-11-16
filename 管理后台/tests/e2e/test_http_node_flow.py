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
    """自己起一轮 worker 催进度。⚠️ 模式要跟常驻服务一致:HTTP 步骤选了真连接 → 这次运行记 live;
    一个 MODEL_ADAPTER=mock 的 worker 领到 live 的运行会拒收(RUN_MODE_MISMATCH),运行直接失败、一步不记(11-16 首跑栽的)。
    这张图里没有模型步,live 模式的 worker 也不会真调模型;HTTP 那一步按跑法 / 白名单决定发不发。"""
    import subprocess
    sys.path.insert(0, _这)
    import _模型模式 as MM
    模式 = "mock" if MM.模型是mock(基址) else "anthropic"
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"], capture_output=True, text=True, timeout=180, cwd=根,
                   env=dict(os.environ, MODEL_ADAPTER=模式))


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
                                                            "允许的端点": 白名单, "secret_ref": "env://E2E_HTTP_KEY_不存在也行", "鉴权": {"方式": "无"}})
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

print("\n▸ ④ 受理(连接测试跑法)→ worker 跑成(替身:一个字节都没出去)")
# 11-16 晚起:HTTP 步骤选了工具连接 → 这次运行算 live(工具连接没有演示版);要替身得明说「连接测试」跑法(worker 的 _http 按跑法交替身)
c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {}, "跑法": "连接测试"})
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
sys.path.insert(0, _这)
import _模型模式 as _MM  # noqa: E402
服务是mock = _MM.模型是mock(基址)     # CI 以 MODEL_ADAPTER=mock 起服务:受理时整次运行记 mock(不是 live),真发送那一支验不出来
ck("HTTP 那一步交的是替身(结束节点交出的模式 = mock),而这次运行本身记成 live(选了真连接;服务是 mock 模式时记 mock)",
   出了.get("模式") == "mock" and (行 or {}).get("execution_mode") == ("mock" if 服务是mock else "live"), (出了, dict(行 or {}), 服务是mock))
ck("步骤记录里 h 这一步 succeeded、没有错误码", any(x["node_id"] == "h" and x["status"] == "succeeded" and not x["error_code"] for x in 步), [dict(x) for x in 步])

print("\n▸ ⑥ 真跑一支(正常跑法):白名单登记的是内网地址 → 发送前被出网策略拦下,一个字节都没出去")
# 端到端能真验的只有「解析落禁区」这一道(目标是本机):不跟重定向 / 凭据不进记录那两道要有外网假服务才打得到,
# 由 tests/orchestration/test_http_node.py 在进程内用假发送验;这里不硬凑
c, b2 = 打("POST", P + "/capability-connections", "U001", 体={"名字": f"e2e HTTP 内网连接 {uuid.uuid4().hex[:6]}", "适配器": "http",
                                                             "允许的端点": ["http://127.0.0.1:9/v1"], "secret_ref": "env://E2E_HTTP_KEY_不存在也行"})
cid2 = (b2 or {}).get("id")
ck("登记一条白名单指向本机的连接(登记不拦 —— 拦在发送那一刻,登记时没有解析也不该解析)", c == 201 and bool(cid2), (c, b2))
c, w2 = 打("POST", P + "/workflows", 体={"名称": f"e2e HTTP 内网 {uuid.uuid4().hex[:6]}", "模板": "空白"})
wid2 = (w2 or {}).get("id")
c, d2 = 打("GET", P + f"/workflows/{wid2}")
定义2 = 图(dict((d2 or {}).get("草稿", {}).get("定义") or {}), connection_id=cid2)
c, _ = 打("PATCH", P + f"/workflows/{wid2}/draft", 体={"定义": 定义2}, 头={"If-Match": str(d2["草稿"]["revision"])})
c, r2 = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid2, "输入": {}})
rid2 = (r2 or {}).get("resource_id")
ck("正常跑法受理 202(受理不解析地址)", c == 202 and bool(rid2), (c, r2))
st2 = 等到(rid2, ("succeeded", "failed", "cancelled")) if rid2 else None
with 事务() as cx:
    行2 = cx.execute(text("select status, execution_mode, output_ref from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid2}).mappings().first() if rid2 else None
    步2 = cx.execute(text("select node_id, status, error_code, error_detail from run_steps where project_id=:p and execution_run_id=:i order by created_at"),
                     {"p": 项目, "i": rid2}).mappings().all() if rid2 else []
h2 = next((dict(x) for x in 步2 if x["node_id"] == "h"), {})
if 服务是mock:
    print(f"  ⏸ 服务是 mock 模式,整次运行记 mock、HTTP 那一步交替身 —— 真发送那一支**这次验不出来,不算通过**(本机 anthropic 模式照验)  实际:{st2} / {dict(行2 or {})}")
    ck("(mock 服务)运行照常跑成,替身地址 = 白名单 + 路径 + 查询串", st2 == "succeeded" and (行2 or {}).get("execution_mode") == "mock", (st2, dict(行2 or {})))
else:
    ck("运行记成 live、结果 failed;h 这一步 failed 且错误码 = HTTP_TARGET_FORBIDDEN(解析落本机 / 内网)",
       st2 == "failed" and (行2 or {}).get("execution_mode") == "live" and h2.get("status") == "failed" and h2.get("error_code") == "HTTP_TARGET_FORBIDDEN",
       (st2, dict(行2 or {}), h2))
    ck("被拒的错误详情里说清了「一个字节都没发出去」这一类,且不含凭据定位符原文", "没发" in json.dumps(h2.get("error_detail"), ensure_ascii=False) and "E2E_HTTP_KEY" not in json.dumps(h2.get("error_detail"), ensure_ascii=False), h2.get("error_detail"))

print("\n▸ ⑤ 收尾")
c3, _ = 打("DELETE", P + f"/workflows/{wid2}", "U001")
with 事务() as cx:
    cx.execute(text("update capability_connections set archived_at=coalesce(archived_at, now()) where project_id=:p and id=:i"), {"p": 项目, "i": cid2})
    cx.execute(text("update workflows set archived_at=coalesce(archived_at, now()) where project_id=:p and id=:i"), {"p": 项目, "i": wid2})
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
