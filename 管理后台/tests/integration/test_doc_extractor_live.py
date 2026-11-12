#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档提取器的 document 适配器(`workers/worker.py::读上传`)—— **真库 + 真存储**(11-12)。

编排层那份(tests/orchestration/test_doc_extractor_node.py)用内存里的假适配器,验不到两件只有真环境才有的事:
  ① **只查这次运行所在的项目**:uploads 的主键是 (project_id, id),同一个编号可以在两个项目里各有一条 ——
     B 项目的编号拿到 A 项目的运行里,必须当「找不到」,不读出 B 的文字
  ② 字节真的从对象存储读出来;库里有、存储里没有 → 明确失败(DOC_READ_FAILED),不是空串
外加:没校验过的上传不读字节、整条图跑下来文本对。

对象存储指到一个临时目录(OBJECT_STORE_ROOT),库里的东西在一个事务里摆、**最后回滚** —— 不留任何东西。
"""
import os
import shutil
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
临时根 = tempfile.mkdtemp(prefix="doc-extract-")
os.environ["OBJECT_STORE_ROOT"] = 临时根          # ⚠️ 必须在 import storage 之前:它在导入时读根目录
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(ROOT, "workers"))

from sqlalchemy import create_engine, insert, text  # noqa: E402
import models as M  # noqa: E402
import storage as OS_  # noqa: E402
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import worker as W  # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 新(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:8]}"


出S = {"type": "object", "properties": {"t": {}}, "required": ["t"], "additionalProperties": False}
图 = {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出S, "nodes": [
    {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {"文件": {}}, "required": ["文件"]}}},
    {"id": "doc", "type": "doc_extractor", "config": {"bindings": {"文件": {"source": "input", "pointer": "/文件"}}}},
    {"id": "end", "type": "end", "config": {"output_schema": 出S, "bindings": {"t": {"source": "node", "node_id": "doc", "pointer": "/文本"}}}}],
    "edges": [{"source": "start", "target": "doc", "port": "success"}, {"source": "doc", "target": "end", "port": "success"}]}
计划 = CP.编译(图, 依赖存在=lambda 种类, i: True)

assert os.path.abspath(OS_.根) == os.path.abspath(临时根), f"对象存储没指到临时目录({OS_.根})—— 不往真存储里写"
with eng.connect() as _c0:
    前计数 = _c0.execute(text("select count(*) from uploads")).scalar()

print("▸ 文档提取器 · 真库真存储(只查本项目 / 读字节 / 存储里没有就失败)")
c = eng.connect()
tx = c.begin()
try:
    org, A, B = 新("org"), 新("projA"), 新("projB")
    c.execute(insert(M.表们["organizations"]).values(id=org, name="测试组织", status="active", created_at=text("now()")))
    for p in (A, B):
        c.execute(insert(M.表们["projects"]).values(id=p, organization_id=org, name=p, status="active", kind_code="测试", created_at=text("now()")))

    def 摆(项目, 号, 名, 状态, 内容):
        键 = OS_.建键(项目id=项目, 上传id=号, 文件名=名, 年月="2026-11")
        if 内容 is not None:
            OS_.写入(键, 内容)
        c.execute(text("""insert into uploads (id, organization_id, project_id, created_at, updated_at, revision,
                            file_name, byte_count, content_type, object_key, status)
                          values (:i, :o, :p, now(), now(), 1, :n, :b, 'text/markdown', :k, :s)"""),
                  {"i": 号, "o": org, "p": 项目, "n": 名, "b": len(内容 or b""), "k": 键, "s": 状态})

    同号 = 新("up")
    摆(A, "up_a1", "量体须知.md", "已校验", "肩宽量两肩点之间。".encode("utf-8"))
    摆(B, 同号, "B的报价.md", "已校验", "B 项目的机密报价".encode("utf-8"))
    摆(A, "up_wait", "草稿.md", "已上传", "还没校验".encode("utf-8"))
    摆(A, "up_lost", "丢了.md", "已校验", None)          # 库里有、存储里没有

    读 = lambda 号: W.读上传(c, A, 号)
    跑 = lambda 文件: RN.跑一张图(计划, {"文件": 文件}, 适配器={"document": 读}, run_id="live")
    码 = lambda r: {s["node_id"]: s for s in r["步骤"]}["doc"].get("error_code")

    r = 跑("up_a1")
    ck("本项目校验过的上传:整条跑下来文本就是存储里那份字节", r["执行状态"] == "succeeded" and r["输出"] == {"t": "肩宽量两肩点之间。"}, r)
    ck("B 项目的编号在 A 的运行里 → 适配器返回 None(不读出 B 的文字)", 读(同号) is None, 读(同号))
    r = 跑(同号)
    ck("  …整条跑下来 → DOC_NOT_FOUND,输出里没有 B 的内容", 码(r) == "DOC_NOT_FOUND" and "机密" not in str(r), (码(r), r["输出"]))
    ck("  对照:同一个编号在 B 项目里读得到(证明上一条拦的是项目,不是编号本身不存在)",
       (W.读上传(c, B, 同号) or {}).get("字节") == "B 项目的机密报价".encode("utf-8"))
    w = 读("up_wait")
    ck("没校验过的上传:记录给出来但不读字节", w and w["status"] == "已上传" and "字节" not in w, w)
    ck("  …整条跑下来 → DOC_NOT_VERIFIED", 码(跑("up_wait")) == "DOC_NOT_VERIFIED")
    ck("库里有、存储里没有 → DOC_READ_FAILED(不是空串)", 码(跑("up_lost")) == "DOC_READ_FAILED")
    ck("完全不存在的编号 → DOC_NOT_FOUND", 码(跑("up_没有这个")) == "DOC_NOT_FOUND")
finally:
    tx.rollback()
    c.close()
    shutil.rmtree(临时根, ignore_errors=True)

with eng.connect() as _c1:
    后计数 = _c1.execute(text("select count(*) from uploads")).scalar()
ck(f"跑完库里 uploads 条数没变({前计数} → {后计数}),临时存储已删", 前计数 == 后计数 and not os.path.exists(临时根))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
