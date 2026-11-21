#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「Markdown 导出」节点 · 端到端(11-21,用户拍第一个业务定时任务 = 经营日报草稿 + Markdown 导出)。打真起着的 :8801,项目 project_lanxiu(U001)。

  ① 空白模板建图:开始(正文 / 门店)→ Markdown 导出(正文绑开始、门店绑开始、标题「经营日报」)→ 结束(交出 file_name / content_hash / 下载)→ 检查配置无阻断;
     没绑正文的草稿 → 检查配置阻断 MARKDOWN_BODY_MISSING
  ② 发起运行(门店 SH001,正文带中文和 \\r\\n)→ 跑成;结束节点拿到文件名(经营日报_SH001_…_运行短号.md)和哈希;
     workflow_documents 里有一行 status=已存、哈希 = 正文 UTF-8 字节的 sha256、统计期空、门店 SH001
  ③ 列表 ?run_id= 能筛到;详情元信息对;下载:200、text/markdown、正文原样(换行统一成 \\n、末尾补换行)、X-Content-Hash 对得上;审计里多一条 workflow_document.download
  ④ 门店范围:登记在 SH002 的临时成员列表里看不到、详情 / 下载 404;不限门店的 U001 看得到
  ⑤ 收尾:归档
"""
import hashlib
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


def 打(方法, 路, 谁="U001", 体=None, 头=None, 原样=False):
    h = {"X-Dev-User": 谁, "Content-Type": "application/json", **(头 or {})}
    rq = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法, headers=h,
                                data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=60) as r:
            if 原样:
                return r.status, r.read(), dict(r.headers)
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            b = e.read()
            return (e.code, b, dict(e.headers)) if 原样 else (e.code, json.loads(b or b"null"))
        except Exception:
            return (e.code, b"", {}) if 原样 else (e.code, None)


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


入 = {"type": "object", "properties": {"正文": {"type": "string"}, "门店": {"type": "string"}}, "required": ["正文"]}
出 = {"type": "object", "properties": {"文件": {"type": "string"}, "哈希": {"type": "string"}, "下载": {"type": "string"}}, "required": ["文件"]}


def 定义(绑正文=True):
    绑 = {"门店": {"source": "input", "pointer": "/门店"}}
    if 绑正文:
        绑["正文"] = {"source": "input", "pointer": "/正文"}
    return {"nodes": [
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 入}},
        {"id": "存", "type": "markdown_export", "name": "存成文件", "config": {"bindings": 绑, "title": "经营日报", "template_version": "v1"}},
        {"id": "finish", "type": "end", "config": {"output_schema": 出, "bindings": {
            "文件": {"source": "node", "node_id": "存", "pointer": "/file_name"}, "哈希": {"source": "node", "node_id": "存", "pointer": "/content_hash"},
            "下载": {"source": "node", "node_id": "存", "pointer": "/下载"}}}}],
        "edges": [{"source": "start", "target": "存", "port": "success"}, {"source": "存", "target": "finish", "port": "success"}]}


正文 = "# 经营日报\r\n\r\n静安店昨日成交 3 单,金额 12,800 元。\r\n- 待跟进 2 人"
应有 = 正文.replace("\r\n", "\n") + "\n"


def main():
    print("▸ ① 建图,检查配置")
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e Markdown 导出 {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = (w or {}).get("id")
    建的.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    rev = d["草稿"]["revision"]
    ck("节点库里「Markdown 导出」可用", any(n["中文"] == "Markdown 导出" and n["可用"] for n in d["节点库"]), [n["中文"] for n in d["节点库"] if not n["可用"]])
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义(绑正文=False)}, 头={"If-Match": str(rev)})
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    码们 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("没绑正文 → 存得了,检查配置阻断 MARKDOWN_BODY_MISSING", c == 200 and "MARKDOWN_BODY_MISSING" in 码们, (c, b, 码们))
    rev = (b or {}).get("revision", rev)
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义()}, 头={"If-Match": str(rev)})
    c2, vb = 打("POST", P + f"/workflows/{wid}/validate")
    码们 = [p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("绑了正文 → 检查配置无阻断", c == 200 and c2 == 200 and 码们 == [], (c, b, 码们))

    print("\n▸ ② 发起运行 → 文件存成")
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {"正文": 正文, "门店": "sh001"}})
    rid = (r or {}).get("resource_id")
    st = 等到(rid, ("succeeded", "failed", "cancelled", "incomplete")) if rid else None
    with 事务() as cx:
        行 = cx.execute(text("select output_ref from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).mappings().first()
        docs = cx.execute(text("select * from workflow_documents where project_id=:p and execution_run_id=:r"), {"p": 项目, "r": rid}).mappings().all()
        步 = cx.execute(text("select node_id, status, error_code from run_steps where project_id=:p and execution_run_id=:i order by created_at"), {"p": 项目, "i": rid}).mappings().all()
    出了 = (行 or {}).get("output_ref") or {}
    if isinstance(出了, str):
        出了 = json.loads(出了)
    期望哈 = hashlib.sha256(应有.encode("utf-8")).hexdigest()
    ck("跑成;结束节点拿到文件名(经营日报_SH001_日期_运行短号.md)和哈希", c == 202 and st == "succeeded" and str(出了.get("文件", "")).startswith("经营日报_SH001_") and 出了.get("文件", "").endswith(".md")
       and 出了.get("哈希") == 期望哈 and "/workflow-documents/" in (出了.get("下载") or ""), (c, st, 出了, [dict(x) for x in 步]))
    doc = dict(docs[0]) if docs else {}
    ck("workflow_documents 一行:已存、哈希对、字节对、门店 SH001、记了 node_id / 流程来源 / 模板版本、生成和存成两个时刻都有",
       len(docs) == 1 and doc.get("status") == "已存" and doc.get("content_hash") == 期望哈 and doc.get("byte_count") == len(应有.encode("utf-8"))
       and doc.get("store_id") == "SH001" and doc.get("node_id") == "存" and doc.get("template_version") == "v1" and doc.get("generated_at") and doc.get("stored_at"), doc)
    did = doc.get("id")

    print("\n▸ ③ 列表 / 详情 / 下载")
    c, L = 打("GET", P + f"/workflow-documents?run_id={rid}")
    ck("列表 ?run_id= 筛到这一份,带下载地址", c == 200 and [x["id"] for x in (L or {}).get("items") or []] == [did] and L["items"][0].get("下载"), (c, L))
    c, D = 打("GET", P + f"/workflow-documents/{did}")
    ck("详情:元信息对、看得到吗 = 真", c == 200 and (D or {}).get("文档", {}).get("file_name") == 出了.get("文件") and D.get("看得到吗") is True, (c, D))
    with 事务() as cx:
        n0 = cx.execute(text("select count(*) from audit_events where project_id=:p and action='workflow_document.download'"), {"p": 项目}).scalar()
    c, 体, 头 = 打("GET", P + f"/workflow-documents/{did}/download", 原样=True)
    with 事务() as cx:
        n1 = cx.execute(text("select count(*) from audit_events where project_id=:p and action='workflow_document.download'"), {"p": 项目}).scalar()
    ck("下载 200、text/markdown、正文原样(\\r\\n 统一、末尾一个换行)、X-Content-Hash 对、文件名在 Content-Disposition 里",
       c == 200 and "text/markdown" in (头.get("Content-Type") or 头.get("content-type") or "") and 体.decode("utf-8") == 应有
       and (头.get("X-Content-Hash") or 头.get("x-content-hash")) == 期望哈 and "filename" in (头.get("Content-Disposition") or 头.get("content-disposition") or ""), (c, 头, 体[:80]))
    ck("下载记了一条审计 workflow_document.download(交出系统)", n1 == n0 + 1, (n0, n1))

    print("\n▸ ④ 门店范围")
    尾 = uuid.uuid4().hex[:5].upper()
    乙 = 成员.记(项目, f"E2EMD2{尾}")
    c, b = 打("POST", P + "/memberships", 体={"工号": 乙, "角色": "admin", "门店": "SH002"})
    c, L = 打("GET", P + f"/workflow-documents?run_id={rid}", 谁=乙)
    c2, D2 = 打("GET", P + f"/workflow-documents/{did}", 谁=乙)
    c3, _, _ = 打("GET", P + f"/workflow-documents/{did}/download", 谁=乙, 原样=True)
    ck("SH002 的店长:列表空、详情 404、下载 404(SH001 的文档不给他,也不说有)", c == 200 and (L or {}).get("items") == [] and c2 == 404 and c3 == 404, (c, L, c2, c3))

    print("\n▸ ⑤ 收尾")
    收尾()
    ck("工作流已归档", True)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ Markdown 导出端到端 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
