"""暂停检查点(11-18,用户拍「运行页暂停 / 取消 / 核实接执行侧」)。

体检查实:runctl 把运行写成 pause_requested / cancel_requested 之后,**执行侧一个字都不读** ——
正在跑的照跑到底,没在跑的永远停在「请求中」。修法是给 `runner.跑一张图` 加 `要暂停吗` 回调,
每到一个节点边界问一次;worker 那边把它接到 execution_runs 的两个标记上(worker 要库,不在这份离线测试里)。

这份只验执行引擎这一半,离线、不碰库:
  ① 回调从第二个节点起说「要停」→ 运行停成 paused,检查点停在**还没跑的那一步**(不是已跑完的那一步)
  ② 停下时那一步没执行(模型没被调)—— 暂停不能多花一次钱
  ③ 拿检查点恢复(结果 None)→ 从那一步接着跑到成功,模型**只调一次**;恢复时不把 {} 注入成那一步的输出
  ④ 回调一直说「不停」→ 和没传回调时结果一样(不传回调的老路径也照旧)
  ⑤ 回调抛异常(worker 里取消就是这么抛的)→ 原样抛出去,不被当成节点失败吞掉
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
图 = {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文,
     "nodes": [{"id": "start", "type": "start", "config": {"input_schema": {
                   "type": "object", "properties": {"问": {"type": "string"}}, "required": ["问"]}}},
               {"id": "llm", "type": "llm", "config": {"connection_version_id": "cv1", "prompt_version_id": "p1",
                                                      "output_schema": 文,
                                                      "bindings": {"问": {"source": "input", "pointer": "/问"}}}},
               {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {
                   "text": {"source": "node", "node_id": "llm", "pointer": "/text"}}}}],
     "edges": [{"source": "start", "target": "llm", "port": "success"},
               {"source": "llm", "target": "end", "port": "success"}]}
计划 = CP.编译(图, 依赖存在=lambda 种类, i: True)


def 跑(要暂停吗=None, 恢复=None, 调用数=None):
    调用数 = 调用数 if 调用数 is not None else []
    事件 = []

    def 模型(cfg, 实参):
        调用数.append(1)
        return {"text": "答:" + str(实参.get("问"))}
    r = RN.跑一张图(计划, {"问": "你好"}, 适配器={"llm": 模型},
                  记事=lambda 名, 载: 事件.append((名, 载)), run_id="r",
                  恢复=恢复, 要暂停吗=要暂停吗)
    return r, 事件, 调用数


print("▸ ① 第二个节点前说「要停」→ paused,检查点停在还没跑的那一步")
问了 = []


def 第二步起停():
    问了.append(1)
    return len(问了) >= 2          # 第一次(start 之前)不停,第二次(llm 之前)停


r, 事, 调 = 跑(要暂停吗=第二步起停)
ck("执行状态是 paused", r["执行状态"] == "paused", 1, r["执行状态"])
点 = r.get("检查点") or {}
ck("检查点停在 llm(还没跑的那一步),不是 start", 点.get("从") == "llm", 1, 点.get("从"))
ck("检查点的等待种类是 pause", (点.get("等待") or {}).get("种类") == "pause", 1, 点.get("等待"))
ck("记了一条 run.pause_checkpoint 事件", any(名 == "run.pause_checkpoint" for 名, _ in 事), len(事), [名 for 名, _ in 事])
print("▸ ② 停下时那一步没执行 —— 模型没被调")
ck("模型调用数 0", len(调) == 0, 1, len(调))
ck("llm 不在「已完成」里(恢复时要重新跑它)", "llm" not in (点.get("已完成") or {}), 1, 点.get("已完成"))
ck("start 的输出留在检查点里", "start" in (点.get("节点输出") or {}), 1, list((点.get("节点输出") or {}).keys()))

print("▸ ③ 拿检查点恢复 → 从 llm 接着跑到成功,模型只调一次")
r2, 事2, 调2 = 跑(恢复={**点, "结果": None})
ck("恢复后运行成功", r2["执行状态"] == "succeeded", 1, (r2["执行状态"], r2.get("完成原因")))
ck("输出是模型真答的,不是注入的空 {}", (r2["输出"] or {}).get("text") == "答:你好", 1, r2["输出"])
ck("模型恰好调了一次", len(调2) == 1, 1, len(调2))
ck("start 没有被重跑(恢复用的是检查点里的输出)", not any(名 == "node.started" and 载.get("node_id") == "start" for 名, 载 in 事2), len(事2))

print("▸ ④ 回调一直说「不停」→ 和不传回调一样")
r3, _, 调3 = 跑(要暂停吗=lambda: False)
r4, _, 调4 = 跑()
ck("两边都成功、输出一样", r3["执行状态"] == r4["执行状态"] == "succeeded" and r3["输出"] == r4["输出"], 2, (r3["执行状态"], r4["执行状态"]))
ck("两边模型都只调一次", len(调3) == 1 and len(调4) == 1, 2, (len(调3), len(调4)))

print("▸ ⑤ 回调抛异常(取消就是这么抛的)→ 原样抛出,不被吞成节点失败")


class 取消了(Exception):
    pass


def 抛():
    raise 取消了()


try:
    跑(要暂停吗=抛)
    ck("抛出去了", False, 1, "没抛")
except 取消了:
    ck("抛出去了(是同一个异常类型)", True, 1)
except Exception as e:  # noqa: BLE001
    ck("抛出去了", False, 1, f"抛的是别的:{type(e).__name__}: {e}")

print()
print(f"过 {len(过)} · 挂 {len(挂)}" + (f" —— {挂}" if 挂 else ""))
sys.exit(1 if 挂 else 0)
