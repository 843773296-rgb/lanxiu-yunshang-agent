#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「Markdown 导出」节点(11-21,用户拍第一个业务定时任务 = 经营日报草稿 + Markdown 导出)—— 纯函数 + 校验器 + 登记,不碰库不碰文件。

  ① 文件名服务端生成:路径分隔符 / 控制字符 / 空白压掉,段没有就跳过,后缀 .md;不接受 ../ 这类逃逸
  ② 正文:字串原样、结构按 JSON 排版、None → 空;统一换行、末尾一个换行;哈希 = 字节的 sha256
  ③ 校验器:没绑「正文」→ 阻断 MARKDOWN_BODY_MISSING;绑了 → 不报;别的节点不受影响
  ④ 登记:dsl 里是已实现、调用外部、端口 成功 / 失败;worker 适配器表里有它;结束节点能绑它的结果(编译得过)
"""
import os
import re
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import 文档导出 as X  # noqa: E402
import validator as V  # noqa: E402
import compiler as CP  # noqa: E402
import dsl as DS  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


print("▸ ① 文件名")
例 = [(("经营日报", "SH001", "2026-11-20", "run-abc12345"), "经营日报_SH001_2026-11-20_run-abc12345.md"),
      (("经营日报", None, None, None), "经营日报.md"),
      (("../../etc/passwd", "a/b", "2026-11-20", "x"), "etc_passwd_a_b_2026-11-20_x.md"),
      (("", "", "", ""), "文档.md"),
      (("日 报:草稿*", "SH001", "2026-11-20", "r1"), "日_报_草稿_SH001_2026-11-20_r1.md")]
坏 = [(入, X.文件名(*入), 期) for 入, 期 in 例 if X.文件名(*入) != 期]
ck("业务名_门店_统计日期_运行短号.md;空段跳过;分隔符 / 控制字符 / 空白压成下划线;../ 逃不出去", not 坏, len(例), 坏)
ck("文件名里绝不出现 / 或 ..", all("/" not in X.文件名(*入) and ".." not in X.文件名(*入) for 入, _ in 例) and not re.search(r"[\x00-\x1f]", X.文件名("a\x00b\nc")), len(例) + 1)
ck("太长的段截断(单段 ≤ 60)", len(X.文件名("汉" * 200)) <= 64, 1, len(X.文件名("汉" * 200)))

print("\n▸ ② 正文与哈希")
ck("字串原样 + 末尾补换行;\\r\\n 统一成 \\n", X.正文转文本("# 标题\r\n正文") == "# 标题\n正文\n" and X.正文转文本("a\n") == "a\n", 2)
ck("结构按 JSON 排版(中文不转义、缩进 2)", X.正文转文本({"店": "静安", "n": 1}) == '{\n  "店": "静安",\n  "n": 1\n}\n', 1, X.正文转文本({"店": "静安", "n": 1}))
ck("None → 只有一个换行(空文件也是合法文件,由适配器决定要不要拒)", X.正文转文本(None) == "\n", 1)
b, h, n = X.字节与哈希("汉\n")
import hashlib
ck("哈希 = UTF-8 字节的 sha256;字节数按 UTF-8 算", h == hashlib.sha256("汉\n".encode("utf-8")).hexdigest() and n == 4 and b == "汉\n".encode("utf-8"), 1)
ck("统计期从绑定来的值里取,缺就空;运行短号取末 8 位", X.统计期({"统计起": "2026-11-20", "统计止": "2026-11-20"}) == {"起": "2026-11-20", "止": "2026-11-20"}
   and X.统计期({}) == {"起": None, "止": None} and X.运行短号("run_0123456789abcdef") == "89abcdef", 3)

print("\n▸ ③ 校验器")
文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
入 = {"type": "object", "properties": {"正文": {"type": "string"}, "门店": {"type": "string"}}, "required": ["正文"]}


def 图(绑):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文,
            "nodes": [{"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 入}},
                      {"id": "存", "type": "markdown_export", "name": "存成文件", "config": {"bindings": 绑, "title": "经营日报"}},
                      {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "存", "pointer": "/file_name"}}}}],
            "edges": [{"source": "start", "target": "存", "port": "success"}, {"source": "存", "target": "end", "port": "success"}]}


校 = lambda g: V.校验(g, 依赖存在=lambda 种类, i: True)  # noqa: E731
码们 = lambda 问, 级=None: [p["code"] for p in 问 if 级 is None or p["级别"] == 级]  # noqa: E731
好 = 图({"正文": {"source": "input", "pointer": "/正文"}, "门店": {"source": "input", "pointer": "/门店"}})
问 = 校(好)
ck("绑了正文 → 没有阻断(节点登记过、端口认得、结束能取它的 file_name)", not 码们(问, V.阻断), 1, 码们(问))
问 = 校(图({"门店": {"source": "input", "pointer": "/门店"}}))
ck("没绑正文 → 阻断 MARKDOWN_BODY_MISSING,报在那个节点上", "MARKDOWN_BODY_MISSING" in 码们(问, V.阻断)
   and any(p["code"] == "MARKDOWN_BODY_MISSING" and p.get("node_id") == "存" for p in 问), 1, 码们(问))
ck("别的节点不受影响(规矩只管 markdown_export)", "MARKDOWN_BODY_MISSING" not in 码们(校({**好, "nodes": [n for n in 好["nodes"] if n["id"] != "存"],
   "edges": [{"source": "start", "target": "end", "port": "success"}]})), 1)

print("\n▸ ④ 登记")
元 = next((n for n in DS.节点表 if n["名"] == "markdown_export"), None)
ck("dsl 登记:已实现、调用外部、端口 = 成功 / 失败、必填 bindings", 元 and 元["实现"] == DS.已实现 and 元["调用外部"] is True
   and set(元["端口"]) == {DS.成功, DS.失败} and "bindings" in 元["必填"], 1, 元)
ck("编译得过(端口 / 绑定都认)", bool(CP.编译(好, 依赖存在=lambda 种类, i: True)), 1)
w = open(os.path.join(根, "workers", "worker.py"), encoding="utf-8").read()
ck("worker 适配器表里有 markdown_export,适配器写完回读核哈希、对不上按失败算", '"markdown_export": _markdown_export' in w and "DOCUMENT_HASH_MISMATCH" in w and "_ST.读出(键)" in w, 3)
a = open(os.path.join(根, "services", "api", "app", "documents_api.py"), encoding="utf-8").read()
ck("下载接口读出来再算一次哈希、对不上不给;走 _审计(交出系统)", "DOCUMENT_HASH_MISMATCH" in a and "_审计(c, me, \"workflow_document.download\"" in a, 2)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ Markdown 导出 {len(过)} 条全过")
