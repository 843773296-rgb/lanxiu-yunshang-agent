#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行测试 —— **预期激活路径是人工写的,模型响应是脚本化的**。

## 判据的两头都要是外部的

规格附录 C.3 对这一层的两个要求:

  · 图夹具:「真值来源:**独立人工预期路径**,不由编译器生成」
  · 脚本化模型响应:「固定响应序列与 call_id……**每轮清空响应游标**」

所以每个 case 写三样:输入、脚本化的模型回答、**我手写的预期激活路径**。
「实际走了哪些节点」和「我以为它会走哪些节点」对不上就红。

## 为什么「跳过的节点」也要断言

§8:「支路 `skipped` 与 `failed` 不同;未激活支路不能阻塞条件汇合,
**也不能作为成功完成的工作计入**」。

只断言「走过的路径」的话,一个把所有节点都跑一遍的执行器也能通过 ——
它走的路径是预期路径的**超集**。所以两边都断言:该走的走了,该跳的跳了。
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
import dsl as DS  # noqa: E402

夹具 = json.load(open(os.path.join(根, "fixtures", "orchestration",
                                  "图校验夹具.json"), encoding="utf-8"))["夹具"]
过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


class 脚本模型:
    """按**固定顺序**回答的 mock。游标每轮从 0 开始(附录 C.3)。

    它还记下自己被调了几次 —— 「调用前拦截,不消耗模型」那条用例的判定方式
    就是**模型调用计数**,而计数必须来自模型这一侧,不能来自被测执行器自报。
    """

    def __init__(self, 回答们):
        self.回答们, self.游标, self.被调 = list(回答们), 0, []

    def __call__(self, cfg, 实参):
        self.被调.append({"prompt": cfg.get("prompt_version_id"), "入": 实参})
        if self.游标 >= len(self.回答们):
            raise AssertionError(
                f"脚本用完了,但执行器又调了第 {self.游标 + 1} 次 —— "
                f"**多调一次不该被当成正常**")
        r = dict(self.回答们[self.游标])
        self.游标 += 1
        r.setdefault("execution_mode", "mock")
        r.setdefault("usage", {"input_tokens": 10, "output_tokens": 20})
        return r


分支图 = 夹具["合法_分支经汇合取值"]["图"]
最小图 = 夹具["合法_最小链"]["图"]
_编 = {}


def 编(图):
    k = json.dumps(图, sort_keys=True, ensure_ascii=False)
    if k not in _编:
        _编[k] = CP.编译(图, 依赖存在=lambda 种类, i: True)
    return _编[k]


def 跑(图, 输入, 回答们, **kw):
    m = 脚本模型(回答们)
    事件 = []
    r = RN.跑一张图(编(图), 输入, 适配器=dict({"llm": m}, **kw.pop("适配器", {})),
                 记事=lambda 种, 载: 事件.append((种, 载)), run_id="rt", **kw)
    return r, m, 事件


# ── ① 条件走不同路径:**预期路径是手写的**(附录 C.2「条件不同路径」)──────
print("▸ 条件走不同路径:**预期激活路径手写**,走过的和跳过的都断言")
用例 = [
    dict(名="中文输入", 回答=[{"lang": "zh", "text": "检测"}, {"text": "中文总结"}],
         预期走过=["start", "detect", "lang", "zh_sum", "merge", "end"],
         预期跳过=["en_sum"], 预期状态="succeeded",
         为什么="中文那一路不该碰翻译/英文总结"),
    dict(名="英文输入", 回答=[{"lang": "en", "text": "检测"}, {"text": "English summary"}],
         预期走过=["start", "detect", "lang", "en_sum", "merge", "end"],
         预期跳过=["zh_sum"], 预期状态="succeeded",
         为什么="对称的另一路"),
    dict(名="未知语言 → 走 else_policy=fail",
         回答=[{"lang": "ja", "text": "检测"}],
         预期走过=["start", "detect", "lang"],
         预期跳过=["zh_sum", "en_sum", "merge", "end"], 预期状态="incomplete",
         为什么="§6.1:没有匹配分支时按显式兜底策略停下。"
               "**不是 succeeded** —— 它没产出必需输出;也不是 failed —— 它没出错"),
]
坏 = []
for u in 用例:
    r, m, _ = 跑(分支图, {"article": "x"}, u["回答"])
    实走, 实跳 = sorted(r["走过的路径"]), sorted(r["跳过的节点"])
    if (实走 != sorted(u["预期走过"]) or 实跳 != sorted(u["预期跳过"])
            or r["执行状态"] != u["预期状态"]):
        坏.append(f"{u['名']}:走过 {实走} / 跳过 {实跳} / 状态 {r['执行状态']}"
                  f"(预期 {sorted(u['预期走过'])} / {sorted(u['预期跳过'])} / {u['预期状态']})")
ck("**三条路径各自只激活预期的节点**(走过的和跳过的都对)", not 坏, len(用例), 坏[:2])

# ── ② 输入缺失:调用前拦截,**不消耗模型**(附录 C.2 第一行)──────────
print("\n▸ 输入缺失:在**发出任何模型调用之前**拦住")
r, m, _ = 跑(最小图, {}, [{"text": "不该被调到"}])
ck("缺必填输入 → 执行失败", r["执行状态"] == "failed", 1, r["完成原因"])
ck("**模型一次都没被调**(判定方式是模型那一侧的计数,不是执行器自报)",
   len(m.被调) == 0 and r["用量"]["模型调用"] == 0, 2,
   f"模型侧 {len(m.被调)} 次 / 执行器记的 {r['用量']['模型调用']} 次")
ck("报错说清了缺哪几个字段(不是一句「输入无效」)",
   any(s.get("error_code") == "INPUT_MISSING" and "article" in
       str(s.get("error_detail")) for s in r["步骤"]), 1)

# ── ③ 普通 LLM 节点返回工具请求:**不擅自执行**(附录 C.2)────────────
print("\n▸ 普通 LLM 节点返回工具请求:不执行,但要**留痕**")
被调工具 = []
r, m, 事件 = 跑(最小图, {"article": "x"},
              [{"text": "好", "tool_calls": [{"name": "send_email",
                                             "arguments": {"to": "谁"}}]}],
              适配器={"tool": lambda cfg, 实参: 被调工具.append(实参) or {}})
ck("**工具适配器一次都没被调**(模型说想调工具 ≠ 后端去调)",
   被调工具 == [], 1, 被调工具)
ck("流程照常跑完(工具请求只是一条数据)", r["执行状态"] == "succeeded", 1)
ck("**留了一条事件说「请求了什么、为什么没执行」**(「明确类型处理」)—— "
   "静默丢掉的话,人会以为是模型不会用工具",
   any(k == "llm.tool_request_ignored" and "send_email" in str(v)
       for k, v in 事件), 1, [k for k, _ in 事件][-4:])

# ── ④ 回合上限:达到上限 ≠ 完成任务(§10.2)──────────────────────────
print("\n▸ 回合上限:**达到上限停止 ≠ 完成任务**")
r, m, _ = 跑(分支图, {"article": "x"},
           [{"lang": "zh", "text": "检测"}, {"text": "不该被调到"}],
           上限={"max_model_turns": 1})
ck("到了上限就不再发新调用", len(m.被调) == 1, 1, len(m.被调))
ck("状态是 incomplete(**不是 succeeded,也不是 failed**)",
   r["执行状态"] == "incomplete", 1, r["执行状态"])
ck("完成原因写的是 max_turns(§16.4 的 completion_reason)",
   r["完成原因"] == "max_turns", 1, r["完成原因"])

# ── ⑤ 转换失败:不静默给 0 ─────────────────────────────────────────
print("\n▸ 字段转换:转不成数字是**节点失败**,不是静默给 0")
转图 = json.loads(json.dumps(最小图))
转图["nodes"].insert(1, {"id": "tr", "type": "transform", "config": {
    "operations": [{"op": "to_number", "from": {"source": "input", "pointer": "/n"},
                    "into": "n"}],
    "output_schema": {"type": "object", "properties": {"n": {"type": "number"}}}}})
转图["edges"] = [{"source": "start", "target": "tr", "port": "success"},
                {"source": "tr", "target": "sum", "port": "success"},
                {"source": "sum", "target": "end", "port": "success"}]
转图["nodes"][0]["config"]["input_schema"] = {
    "type": "object", "properties": {"n": {"type": "string"}}, "required": ["n"]}
转图["nodes"][0]["config"]["input_schema"] = {
    "type": "object",
    "properties": {"n": {"type": "string"}, "article": {"type": "string"}},
    "required": ["n", "article"]}
r, m, _ = 跑(转图, {"n": "十二", "article": "x"}, [{"text": "不该被调到"}])
ck("「十二」转不成数字 → 节点失败,**而且模型没被调**",
   r["执行状态"] == "failed" and len(m.被调) == 0, 2,
   f"{r['完成原因']} / 模型 {len(m.被调)} 次")
r2, m2, _ = 跑(转图, {"n": "12", "article": "x"}, [{"text": "好"}])
ck("对照:「12」能转 → 正常跑完(不是一律失败)",
   r2["执行状态"] == "succeeded", 1, f"{r2['执行状态']} / {r2['完成原因']}")

# ── ⑥ 密钥:两道闸,而且**只能分开测** ────────────────────────────
#
# ⚠️ 这里的测试形状值得说一句。想「编译 → 跑」地测执行器那道闸是**做不到**的:
# 那张图过不了编译器(校验器先拦了 BIND_SECRET_INTO_MODEL)。
#
# 于是有两个选择:给生产代码加一个「跳过校验」的开关去迁就测试,
# 还是把判据拆成两条。**开关会活下来,而且会有人用它** —— 所以拆判据:
#   ① 校验器拦住那张图(正常路径上的第一道);
#   ② `取值()` 这个单元自己对 secret 来源抛(第二道,
#      它只在「有东西绕过校验直接构造了计划」时才起作用 —— 而那正是它存在的理由)。
print("\n▸ 密钥:校验器拦一道,执行器再拦一道(**两道只能分开测**)")
密图 = json.loads(json.dumps(最小图))
密图["nodes"][1]["config"]["bindings"] = {"k": {"source": "secret",
                                              "secret_ref": "sr1"}}
import validator as _V  # noqa: E402
ck("第一道:校验器拦住这张图(所以它根本编译不出来)",
   any(p["code"] == "BIND_SECRET_INTO_MODEL" for p in _V.校验(密图)), 1)
try:
    CP.编译(密图, 依赖存在=lambda 种类, i: True)
    编不出来 = False
except CP.编译失败:
    编不出来 = True
ck("编译器拒绝编译(不合法的图编译出来的「计划」是什么,没人说得清)", 编不出来, 1)
_抛了 = False
try:
    RN.取值({"source": "secret", "secret_ref": "sr1"}, {"input": {}})
except RN.节点失败 as e:
    _抛了 = (e.code == "SECRET_IN_FLOW")
ck("第二道:取值() 自己对 secret 来源抛 —— "
   "**它防的是绕过校验直接构造出来的计划**", _抛了, 1)

# ── ⑦ 取指针:「不存在」和「值是 null」分得开 ────────────────────────
print("\n▸ 取值:「字段不存在」返回 缺失,**不是 None**")
ck("取不到的路径返回 DS.缺失(返回 None 会让下游当成「值是空的」)",
   RN.取指针({"a": 1}, "/b") is DS.缺失, 1)
ck("值真的是 null 就返回 None(两件事分开)",
   RN.取指针({"a": None}, "/a") is None, 1)
ck("数组下标越界也返回 缺失", RN.取指针({"a": [1]}, "/a/3") is DS.缺失, 1)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
