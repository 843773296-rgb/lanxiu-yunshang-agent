#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识检索节点 · 端到端(三期 3-5,11-20 做通)。

11-20 盘点:这个节点能加进图、dsl 标「已实现」,但面板里没地方选资料库、worker 没有它的适配器 —— 跑到就 ADAPTER_MISSING。
这份验**接线**(判据在 tests/orchestration/test_retrieve_node.py):
  ① 搭建资源接口给出资料库(带最新就绪索引)和检索配置版本(带召回设置几项)
  ② 空白模板建图:开始(问题)→ 知识检索(选库、索引、配置,问题绑开始)→ 结束(交出证据 / 召回数 / 模式 / 试跑id)→ 检查配置无阻断
  ③ 检查配置在进程内也核一遍:没绑问题 → RETRIEVE_QUERY_MISSING;没就绪索引 → RETRIEVE_NO_READY_INDEX
  ④ 受理「正常」跑法 → 跑成:服务是真模型模式 → 这次运行记 live、真查到东西(召回数 > 0、证据非空、召回记录里多一条来源「工作流」);
     服务是演示模式(CI)→ 记 mock、交空替身(召回数 0、模式 mock)
  ⑤ 「连接测试」跑法 → 不管服务什么模式都交替身(不花钱、不进召回记录)
  ⑥ 收尾:工作流归档
⚠️ 真模型模式下 ④ 会调一次模型做查询改写(几分钱)+ 本机 onnx 算一次向量;精排跟检索配置走(今天全没配 → 不精排)。
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
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, _这)
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import validator as V  # noqa: E402
import _模型模式 as MM  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")   # 要一个有「已就绪」索引的资料库;澜绣项目有两个
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


服务是mock = MM.模型是mock(基址)


def 跑worker():
    """自己起一轮 worker 催进度;模式跟常驻服务一致(领到 live 的运行的 mock worker 会拒收)。"""
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


def 运行结果(rid):
    with 事务() as cx:
        行 = cx.execute(text("select output_ref, execution_mode, status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).mappings().first()
        步 = cx.execute(text("select node_id, status, error_code, error_detail from run_steps where project_id=:p and execution_run_id=:i order by created_at"),
                        {"p": 项目, "i": rid}).mappings().all()
    出 = (行 or {}).get("output_ref") or {}
    if isinstance(出, str):
        try:
            出 = json.loads(出)
        except Exception:
            出 = {"_原文": 出}
    return dict(行 or {}), 出, [dict(x) for x in 步]


建的 = []


def 收尾():
    for wid in list(建的):
        c, b = 打("POST", P + f"/workflows/{wid}/archive", 体={"理由": "e2e 收尾"})
        if c != 200:
            print(f"  ⚠️ 收尾没归档成 {wid}:{c} {b}")
    建的.clear()


def 图(定义, *, 库, 索引, 配置, 绑问题=True):
    文 = {"type": "object", "properties": {"问题": {"type": "string", "title": "问题"}}, "required": ["问题"]}
    出 = {"type": "object", "properties": {"证据": {"type": "string"}, "召回数": {"type": "integer"}, "模式": {"type": "string"}, "试跑id": {"type": "string"}},
         "required": ["证据"]}
    定义["nodes"] = [
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 文}},
        {"id": "q", "type": "retrieve", "name": "查资料", "config": {
            "knowledge_base_id": 库, "index_build_id": 索引, "retrieval_config_version_id": 配置,
            "bindings": ({"问题": {"source": "input", "pointer": "/问题"}} if 绑问题 else {})}},
        {"id": "finish", "type": "end", "config": {"output_schema": 出, "bindings": {
            "证据": {"source": "node", "node_id": "q", "pointer": "/证据"}, "召回数": {"source": "node", "node_id": "q", "pointer": "/召回数"},
            "模式": {"source": "node", "node_id": "q", "pointer": "/execution_mode"}, "试跑id": {"source": "node", "node_id": "q", "pointer": "/试跑id"}}}},
    ]
    定义["edges"] = [{"source": "start", "target": "q", "port": "success"}, {"source": "q", "target": "finish", "port": "success"}]
    return 定义


def main():
    global 项目, P
    print(f"▸ ① 搭建资源接口给资料库和检索配置(服务{'演示' if 服务是mock else '真模型'}模式)")
    c, 资 = 打("GET", P + "/workflow-resources")
    库们 = (资 or {}).get("资料库") or []
    配们 = (资 or {}).get("检索配置") or []
    有索引的 = [k for k in 库们 if k.get("就绪索引")]
    if not 有索引的 and 项目 != "project_demo_a":
        # GitHub CI 是从零建的新库:澜绣项目只 ingest 了文档、**没建就绪索引**(建索引要真嵌入模型);
        # CI 流水线给演示项目用 tools/seed_retrieval_demo.py 造了一个就绪索引 → 换到那个项目上验同一套判据。
        # 本地共享库的澜绣项目有真索引,走不到这里。11-19 起 CI 这份一直红在这一步、没人看见。
        print(f"  ⚠️ {项目} 没有带就绪索引的资料库 → 改用 project_demo_a 验(前提换了,下面的 ✅ 是在演示项目上验的)")
        项目, P = "project_demo_a", "/api/v1/projects/project_demo_a"
        c, 资 = 打("GET", P + "/workflow-resources")
        库们 = (资 or {}).get("资料库") or []
        配们 = (资 or {}).get("检索配置") or []
        有索引的 = [k for k in 库们 if k.get("就绪索引")]
    ck("资源里有「资料库」,至少一个带最新就绪索引", c == 200 and bool(有索引的), (c, 库们[:3]))
    ck("资源里有「检索配置」,带候选数 / 最终片段数 / 召回方式", bool(配们) and all(k in 配们[0] for k in ("候选数", "最终片段数", "召回方式")), 配们[:2])
    if not (有索引的 and 配们):
        print("❌ 没有能检索的资料库或检索配置 —— **不在没有前提的时候出结论**(先 python tools/ingest_lanxiu.py 建索引)")
        sys.exit(1)
    库 = 有索引的[0]
    配置 = 库.get("索引用的配置") or 配们[0]["id"]

    print("\n▸ ② 空白模板建图:开始 → 知识检索 → 结束,检查配置无阻断")
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 知识检索 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = (w or {}).get("id")
    建的.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = 图(d["草稿"]["定义"], 库=库["id"], 索引=库["就绪索引"], 配置=配置)
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    阻 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("存草稿 200 · 检查配置无阻断(库在、索引在、配置在、问题绑了)", c == 200 and c2 == 200 and 阻 == [], (c, b, c2, 阻))

    print("\n▸ ③ 检查配置在进程内也核一遍")
    def 阻断码(g):
        return sorted({p.get("code") for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p.get("级别") == V.阻断})
    g2 = 图(json.loads(json.dumps(定义)), 库=库["id"], 索引=库["就绪索引"], 配置=配置, 绑问题=False)
    ck("没绑问题 → RETRIEVE_QUERY_MISSING", "RETRIEVE_QUERY_MISSING" in 阻断码(g2), 阻断码(g2))
    g3 = 图(json.loads(json.dumps(定义)), 库=库["id"], 索引=None, 配置=配置)
    ck("没就绪索引 → RETRIEVE_NO_READY_INDEX", "RETRIEVE_NO_READY_INDEX" in 阻断码(g3), 阻断码(g3))

    print("\n▸ ④ 受理「正常」跑法 → 跑成")
    with 事务() as cx:
        之前 = cx.execute(text("select count(*) from retrieval_runs where project_id=:p and source='工作流'"), {"p": 项目}).scalar()
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"问题": "客户给了差评要怎么处理"}})
    rid = (r or {}).get("resource_id")
    ck("受理 202,拿到运行号", c == 202 and bool(rid), (c, r))
    st = 等到(rid, ("succeeded", "failed", "cancelled", "incomplete")) if rid else None
    行, 出, 步 = 运行结果(rid) if rid else ({}, {}, [])
    ck("跑成 succeeded;q 这一步 succeeded、没有错误码", st == "succeeded" and any(x["node_id"] == "q" and x["status"] == "succeeded" and not x["error_code"] for x in 步), (st, 出, 步))
    if 服务是mock:
        ck("演示模式:这次运行记 mock、结束节点交出的模式 mock、召回数 0(空替身,不真查)",
           行.get("execution_mode") == "mock" and 出.get("模式") == "mock" and 出.get("召回数") == 0, (行.get("execution_mode"), 出))
    else:
        ck("真模型模式:这次运行记 live(选了资料库就是要真查)、结束节点交出的模式 live", 行.get("execution_mode") == "live" and 出.get("模式") == "live", (行.get("execution_mode"), 出))
        ck("真查到东西:召回数 > 0、证据非空", (出.get("召回数") or 0) > 0 and bool((出.get("证据") or "").strip()), {k: (str(v)[:80] if v is not None else None) for k, v in 出.items()})
        with 事务() as cx:
            之后 = cx.execute(text("select count(*) from retrieval_runs where project_id=:p and source='工作流'"), {"p": 项目}).scalar()
            那条 = cx.execute(text("select id, source, recall_count from retrieval_runs where project_id=:p and id=:i"), {"p": 项目, "i": 出.get("试跑id")}).mappings().first() if 出.get("试跑id") else None
        ck("召回记录里多了一条,来源「工作流」,就是结束节点交出的那个试跑id", 之后 == 之前 + 1 and 那条 is not None and 那条["source"] == "工作流", (之前, 之后, dict(那条) if 那条 else None))

    print("\n▸ ⑤ 「连接测试」跑法 → 交替身,不管服务什么模式")
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"问题": "客户给了差评要怎么处理"}, "跑法": "连接测试"})
    rid2 = (r or {}).get("resource_id")
    st2 = 等到(rid2, ("succeeded", "failed", "cancelled", "incomplete")) if rid2 else None
    行2, 出2, 步2 = 运行结果(rid2) if rid2 else ({}, {}, [])
    ck("连接测试跑成;模式 mock、召回数 0、没有试跑id(不进召回记录)", st2 == "succeeded" and 出2.get("模式") == "mock" and 出2.get("召回数") == 0 and not 出2.get("试跑id"), (st2, 出2, 步2))

    print("\n▸ ⑥ 收尾")
    收尾()
    ck("工作流已归档", True)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ 知识检索端到端 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
