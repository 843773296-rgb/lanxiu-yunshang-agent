#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行的「业务结果」(10-26,方案 §8.2):流程跑完了 ≠ 业务上合格,用人话分开说。

每种情况手写期望的结论(不是跑一遍抄回来):跑完 → 已完成;跑完但没产出要求的结果 → 已完成,需补充资料;
到上限 → 没做完;某一步失败 → 失败 + 是哪一步 + **那一步自己的报错和下一步**;停着 → 进行中。
另查一条:说给人看的文字里不出现英文错误码(执行状态那行小字里的码不算,那是给技术看的)。
"""
import os
import re
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in ("services/api/app", "services/api/app/contract", "services/api/app/runtime"):
    sys.path.insert(0, os.path.join(根, p))
import workflows_api as W  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 else ''}")
    (过 if 真 else 挂).append(名)


失败步 = [{"status": "succeeded", "node_id": "s"},
          {"status": "failed", "node_id": "extract",
           "error_detail": {"消息": "这一步要用的数据取不到:原文", "建议": "加一个「分支汇合」再取"}}]
用例 = [
    ("succeeded", None, [], None, "已完成"),
    ("incomplete", "missing_evidence", [], None, "已完成,需补充资料"),
    ("incomplete", None, [], None, "已完成,需补充资料"),
    ("incomplete", "max_turns", [], None, "没做完"),
    ("failed", "BIND_MISSING_AT_RUNTIME", 失败步, None, "失败"),
    ("waiting_approval", None, [], {"种类": "human"}, "进行中"),
    ("waiting_external", None, [], {"种类": "external"}, "进行中"),
]
print("▸ 业务结果:每种情况的结论是手写的")
坏 = []
for 状态, 原因, 步, 等, 期望 in 用例:
    r = W._业务结论(状态, 原因, 步, 等)
    if r["结论"] != 期望:
        坏.append((状态, 原因, r["结论"], 期望))
ck("每种情况给出的结论和手写期望一致", not 坏, len(用例), 坏)
r = W._业务结论("failed", "BIND_MISSING_AT_RUNTIME", 失败步, None)
ck("失败时说清是哪一步,并带上那一步自己的报错和下一步",
   r.get("哪一步") == "extract" and "原文" in r["说明"] and "汇合" in (r.get("下一步") or ""), 1, r)
r2 = W._业务结论("failed", "INPUT_MISSING", [{"status": "failed", "node_id": "s", "error_detail": '{"消息": "还有必填的内容没填:article"}'}], None)
ck("那一步的报错存成文字(JSON 串)时也读得出来", "article" in r2["说明"], 1, r2)
r3 = W._业务结论("failed", "NO_MODEL_CONNECTION", [], None)
ck("找不到失败的那一步时,用停止原因的人话兜底,不说空话", r3["说明"] and "模型" in r3["说明"], 1, r3)
英码 = re.compile(r"\b[A-Z][A-Z_]{3,}\b")
露 = [(u[0], u[1]) for u in 用例 for x in [W._业务结论(*u[:4])] if 英码.search(x["说明"] + (x.get("下一步") or ""))]
ck("说给人看的文字里没有英文错误码", not 露, len(用例), 露)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
