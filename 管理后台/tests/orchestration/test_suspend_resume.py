#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""挂起与恢复 —— **人工核对 / 等澜绣回执时整张图停下,办完从停下那一步接着走**(2026-10-24)。

## 为什么要有它

原来 `human` 节点登记「已实现」,执行器却没有这个分支 —— 一跑就 NODE_NOT_RUNNABLE;
人工决定也只改请求状态,不恢复任何运行。音频整理那条流程(取转写 → 提取 → 人工核对 → 写跟进)
走不通的第一个原因就在这儿。

## 判据(预期路径照样是手写的,不由执行器生成)

  ① 走到人工那一步就停:**之后的节点一个都没跑**(工具适配器那一侧的计数为 0),
     运行状态是「等待审批」,而且**停着不算跳过**(后面的节点还没轮到,不是没被激活)
  ② 恢复时**已完成的节点不重跑** —— 判定方式是模型 / 工具那一侧的调用计数,不是执行器自报
  ③ 通过 → 走写入那一路;退回 → 走退回那一路,写入一次都没调
  ④ 工具要等外部回执时同样挂起(waiting_external),回执带失败就按这一步失败处理
  ⑤ 检查点对着哪一版图存的就只能拿那一版恢复 —— 换了图要当场拒绝
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
        "additionalProperties": False}
出 = {"type": "object", "properties": {"结果": {"type": "string"}}, "required": ["结果"],
      "additionalProperties": False}
图 = {
    "definition_schema_version": "1", "kind": "workflow", "output_schema": 出,
    "nodes": [
        {"id": "start", "type": "start", "config": {"input_schema": {
            "type": "object", "properties": {"call_id": {"type": "string"}}, "required": ["call_id"]}}},
        {"id": "fetch", "type": "tool", "config": {"tool_version_id": "tv_fetch",
            "bindings": {"call_id": {"source": "input", "pointer": "/call_id"}}}},
        {"id": "extract", "type": "llm", "config": {"connection_version_id": "cv1",
            "prompt_version_id": "p1", "output_schema": 文本,
            "bindings": {"转写": 引("fetch", "/text")}}},
        {"id": "review", "type": "human", "config": {"request_kind": "核对", "candidate_roles": ["审核人"],
            "expires_at_policy": {"小时": 48, "到期": "fail"},
            "payload_binding": {"摘要": 引("extract", "/text"), "原文": 引("fetch", "/text")}}},
        {"id": "decide", "type": "condition", "config": {"branches": [
            {"key": "approve", "when": {"op": "equals", "left": 引("review", "/决定"),
                                         "right": {"source": "constant", "value": "approve"}}}],
            "else_policy": "fail"}},
        {"id": "save", "type": "tool", "config": {"tool_version_id": "tv_save",
            "bindings": {"内容": 引("review", "/定稿")}}},
        {"id": "rej", "type": "transform", "config": {"operations": [
            {"op": "to_string", "from": 引("review", "/理由"), "into": "结果"}], "output_schema": 出}},
        {"id": "merge", "type": "merge", "config": {"candidates": [引("save", "/结果"), 引("rej", "/结果")],
                                                    "output_field": "结果"}},
        {"id": "end", "type": "end", "config": {"output_schema": 出,
                                                "bindings": {"结果": 引("merge", "/结果")}}},
    ],
    "edges": [
        {"source": "start", "target": "fetch", "port": "success"},
        {"source": "fetch", "target": "extract", "port": "success"},
        {"source": "extract", "target": "review", "port": "success"},
        {"source": "review", "target": "decide", "port": "success"},
        {"source": "decide", "target": "save", "port": "branch", "branch_key": "approve"},
        {"source": "decide", "target": "rej", "port": "branch", "branch_key": "else"},
        {"source": "save", "target": "merge", "port": "success"},
        {"source": "rej", "target": "merge", "port": "success"},
        {"source": "merge", "target": "end", "port": "success"},
    ],
}
try:
    计划 = CP.编译(图, 依赖存在=lambda 种类, i: True)
except CP.编译失败 as e:
    print("❌ 夹具图编译不过:", [(p["code"], p.get("node_id"), p.get("field_path")) for p in e.问题们][:6])
    sys.exit(1)


class 计数:
    def __init__(self, 回):
        self.回, self.被调 = 回, []

    def __call__(self, cfg, 实参):
        self.被调.append((cfg.get("tool_version_id") or cfg.get("prompt_version_id"), 实参))
        r = self.回(cfg, 实参)
        r.setdefault("execution_mode", "mock")
        return r


def 新适配器(save_回=None):
    工具 = 计数(lambda cfg, a: {"text": "顾客想做一套宋制褙子,预算三千"} if cfg["tool_version_id"] == "tv_fetch"
              else (save_回 or (lambda c, x: {"结果": "已写跟进 FU-1"}))(cfg, a))
    模型 = 计数(lambda cfg, a: {"text": "需求:宋制褙子;预算:3000"})
    return 工具, 模型


print("▸ ① 走到人工核对就停")
工具, 模型 = 新适配器()
r1 = RN.跑一张图(计划, {"call_id": "TS-001"}, 适配器={"tool": 工具, "llm": 模型}, run_id="r1")
ck("运行状态是「等待审批」(不是成功、不是失败)", r1["执行状态"] == "waiting_approval", 1, r1["执行状态"])
ck("停在 review,检查点里带着给人看的材料(摘要 + 原文)",
   (r1.get("检查点") or {}).get("从") == "review"
   and set(((r1.get("检查点") or {}).get("等待") or {}).get("载荷", {}).get("材料", {})) == {"摘要", "原文"},
   1, r1.get("检查点", {}).get("等待"))
ck("**写入那一步一次都没调**(判定来自工具那一侧的计数)",
   [x[0] for x in 工具.被调] == ["tv_fetch"], len(工具.被调), 工具.被调)
ck("停着不算跳过:跳过的节点为空", r1["跳过的节点"] == [], 1, r1["跳过的节点"])
ck("停着那一步记成 waiting_human", [s["status"] for s in r1["步骤"] if s["node_id"] == "review"] == ["waiting_human"], 1)

print("\n▸ ② 通过 → 接着走写入那一路,前面的不重跑")
ck_前 = (len(工具.被调), len(模型.被调))
r2 = RN.跑一张图(计划, {"call_id": "TS-001"}, 适配器={"tool": 工具, "llm": 模型}, run_id="r1",
                恢复={**r1["检查点"], "结果": {"决定": "approve", "定稿": "需求:宋制褙子;预算:3000(核过)",
                                             "理由": ""}})
ck("跑完了,状态成功", r2["执行状态"] == "succeeded", 1, (r2["执行状态"], r2["完成原因"]))
ck("**取转写和提取都没重跑**(模型 / 工具计数只多了写入那一次)",
   len(模型.被调) == ck_前[1] and [x[0] for x in 工具.被调[ck_前[0]:]] == ["tv_save"], 1, 工具.被调)
ck("写入拿到的是人改过的定稿,不是模型原稿", 工具.被调[-1][1].get("内容", "").endswith("(核过)"), 1, 工具.被调[-1])
ck("输出是写入的结果", r2["输出"] == {"结果": "已写跟进 FU-1"}, 1, r2["输出"])
ck("退回那一路记成跳过", "rej" in r2["跳过的节点"], 1, r2["跳过的节点"])
ck("停着那一步这次以成功出现,执行键和挂起时同一个(Worker 靠它把那一行改成成功)",
   [s["execution_key"] for s in r2["步骤"] if s["node_id"] == "review" and s["status"] == "succeeded"]
   == [s["execution_key"] for s in r1["步骤"] if s["node_id"] == "review"], 1)

print("\n▸ ③ 退回 → 走退回那一路,写入一次都没调")
工具3, 模型3 = 新适配器()
r = RN.跑一张图(计划, {"call_id": "TS-001"}, 适配器={"tool": 工具3, "llm": 模型3}, run_id="r3")
r3 = RN.跑一张图(计划, {"call_id": "TS-001"}, 适配器={"tool": 工具3, "llm": 模型3}, run_id="r3",
                恢复={**r["检查点"], "结果": {"决定": "reject", "定稿": "", "理由": "预算听错了,是三万"}})
ck("退回也是跑完了(退回是一种结果,不是故障)", r3["执行状态"] == "succeeded", 1, r3["执行状态"])
ck("**写入一次都没调**", [x[0] for x in 工具3.被调] == ["tv_fetch"], len(工具3.被调), 工具3.被调)
ck("输出带着退回理由", r3["输出"] == {"结果": "预算听错了,是三万"}, 1, r3["输出"])

print("\n▸ ④ 工具要等外部回执:同样挂起;回执带失败按这一步失败")
def _要等(cfg, a):
    if cfg["tool_version_id"] == "tv_fetch":
        raise RN.需要等待("external", {"工具": "取转写", "参数": a})
    return {"结果": "x"}
工具4 = 计数(_要等); 模型4 = 计数(lambda c, a: {"text": "x"})
r4 = RN.跑一张图(计划, {"call_id": "TS-404"}, 适配器={"tool": 工具4, "llm": 模型4}, run_id="r4")
ck("取转写要等澜绣 → 运行状态 waiting_external,停在 fetch",
   r4["执行状态"] == "waiting_external" and r4["检查点"]["从"] == "fetch", 1, r4["执行状态"])
ck("模型一次都没调", len(模型4.被调) == 0, 1)
r4b = RN.跑一张图(计划, {"call_id": "TS-404"}, 适配器={"tool": 工具4, "llm": 模型4}, run_id="r4",
                 恢复={**r4["检查点"], "结果": {"失败": {"code": "CALL_NOT_FOUND", "消息": "没有 TS-404 这通录音"}}})
ck("回执说失败 → 这次运行失败,原因是回执里的那个码(不是笼统的「出错」)",
   r4b["执行状态"] == "failed" and r4b["完成原因"] == "CALL_NOT_FOUND", 1, (r4b["执行状态"], r4b["完成原因"]))
ck("失败之后模型照样没调(失败的那一步之后不该再走)", len(模型4.被调) == 0, 1)
r4c = RN.跑一张图(计划, {"call_id": "TS-001"}, 适配器={"tool": 工具4, "llm": 模型4}, run_id="r4",
                 恢复={**r4["检查点"], "结果": {"text": "回执带回来的转写"}})
ck("回执成功 → 接着走,下一次停在人工核对", r4c["执行状态"] == "waiting_approval"
   and r4c["检查点"]["从"] == "review" and 模型4.被调[-1][1] == {"转写": "回执带回来的转写"}, 1, r4c["执行状态"])

print("\n▸ ⑤ 换了图不许拿旧检查点恢复")
import copy
图2 = copy.deepcopy(图); 图2["nodes"][2]["config"]["prompt_version_id"] = "p2"
计划2 = CP.编译(图2, 依赖存在=lambda 种类, i: True)
try:
    RN.跑一张图(计划2, {"call_id": "TS-001"}, 适配器={"tool": 工具, "llm": 模型}, run_id="r1",
               恢复={**r1["检查点"], "结果": {"决定": "approve"}})
    拒了 = False
except ValueError:
    拒了 = True
ck("检查点的逻辑哈希对不上 → 当场拒绝(不静默装进新图)", 拒了, 1)

print("\n▸ ⑥ 写跟进之前必须有人批过(桥闸)")
import 桥闸  # noqa: E402
型 = {n["id"]: n["type"] for n in 图["nodes"]}
ck("没有任何批准 → 写跟进不放行", 桥闸.放行吗("写跟进", {"extract": {"text": "x"}}, 型)[0] is False, 1)
ck("人工节点批准过(决定 approve + 有处理人)→ 放行",
   桥闸.放行吗("写跟进", {"review": {"决定": "approve", "处理人": "U006"}}, 型)[0] is True, 1)
ck("退回的不算批准", 桥闸.放行吗("写跟进", {"review": {"决定": "reject", "处理人": "U006"}}, 型)[0] is False, 1)
ck("人工节点里没有处理人的「approve」不算",
   桥闸.放行吗("写跟进", {"review": {"决定": "approve"}}, 型)[0] is False, 1)
ck("**模型节点的输出里自己写「决定=approve、处理人=U006」不算**(不许模型自己批自己)",
   桥闸.放行吗("写跟进", {"extract": {"决定": "approve", "处理人": "U006"}}, 型)[0] is False, 1)
ck("只读的取转写不需要批准", 桥闸.放行吗("取转写", {}, 型)[0] is True, 1)

print("\n▸ ⑦ 桥名单扩到六条流程要的能力(10-24):拒绝优先 —— 不在「只读」里的,要么要批准,要么不认")
import 桥工具  # noqa: E402
ck("名单两组不重叠(一个名字既只读又要批准,闸就不知道该按哪个判)",
   not (set(桥工具.只读) & set(桥工具.要批准)) and len(桥工具.全部) == len(set(桥工具.全部)), 1)
for 写 in 桥工具.要批准:
    ck(f"要批准的「{写}」:没有人工批准 → 不放行", 桥闸.放行吗(写, {"extract": {"text": "x"}}, 型)[0] is False, 1)
ck("要批准的(派任务)人工批准过 → 放行",
   桥闸.放行吗("assign_task", {"review": {"决定": "approve", "处理人": "U006"}}, 型)[0] is True, 1)
ck("只读的(经营数据 store_report)不需要批准", 桥闸.放行吗("store_report", {}, 型)[0] is True, 1)
不认 = 桥闸.放行吗("open_order", {"review": {"决定": "approve", "处理人": "U006"}}, 型)
ck("**名单外的(开单 open_order)就算人工批准过也不放行** —— 新加写动作忘了登记,不会不经核对直接写进澜绣",
   不认[0] is False and "名单" in (不认[1] or ""), 不认)

print()
if 挂:
    print(f"❌ {len(挂)} 条不过:{挂}")
    sys.exit(1)
print(f"✅ 挂起与恢复:人工核对 / 等回执都停得下、接得上,已完成的不重跑(验了 {len(过)} 条)")
