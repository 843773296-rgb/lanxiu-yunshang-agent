#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流「列表迭代」节点的规则 —— **校验器和执行器都调这一处**(照 Dify「迭代」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 配置长什么样

    bindings:            {"列表": <结构化引用>}      上游给的那个列表(一定要是列表,不是就失败)
    item_output:         <结构化引用,指迭代里面某一步的结果>   每一项做完交出什么(收进「结果」那一位)
    item_failure_policy: "fail" | "continue"         某一项失败时:整步失败 / 留空位接着做下一项
    max_items:           1 到 技术上限 的整数          这一步最多做几项(超了一项都不做,直接失败)

迭代里面的步骤(`container` 指向这个迭代)每一项跑一遍,能在「用到的数据」里取:
    当前项   {"source": "scope", "pointer": "/当前项"}   (也可以往里取:/当前项/金额)
    下标     {"source": "scope", "pointer": "/下标"}     从 0 数,第 1 项的下标是 0(和 Dify 一样)

结果:结果(列表,**和输入一一对应、顺序一致**)/ 个数 / 失败项(列表:哪一项、哪一步、为什么)。

## 为什么串行

一次只做一项,做完一项再做下一项。并行是「并行与汇总」那个节点的事(规格 §6.1 另一行,还没实现),
不在这里偷偷开 —— 并发写同一个循环状态的结果取决于调度顺序,而那在画布上看不出来。

## 为什么「最多做几项」超了就一项都不做

列表多长,进这一步之前就知道。超了还先做前 N 项,会交出一份**看着完整、其实少了尾巴**的结果;
而且前 N 项里每一项可能都调了模型、花了钱。所以超了直接失败,说清「给了几项、上限几项」。
技术上限(`技术上限`)只是一步里能装下的运行记录和检查点大小,**不是业务门槛** ——
业务上一次该处理多少条,由搭流程的人在「最多做几项」里填。

## 某一项失败时(规格 §6.1「单项失败策略」、§6.3「失败项保持占位和错误原因,不默默删除」)

  · fail(默认):这一步失败,走这一步自己的「失败时」出口(没接就整次运行失败),
    错误里写清**是第几项、下标几、哪一步、为什么**。前面做完的几项在这一步的记录里看得到。
  · continue:这一项在「结果」里那一位放 null(**占位,不删** —— 删掉一项后面全体错位,而错位之后的数据看起来完全正常),
    原因记进「失败项」,接着做下一项。
  · 不提供 Dify 的「去掉失败项」:规格明写不许(错位)。
"""

技术上限 = 100          # 一步最多做几项的**技术**上限(运行记录 / 检查点装得下),不是业务门槛
记录里列几项 = 20       # 这一步自己的运行记录里逐项列出几项;多了说清还有几项(每一项的步骤另有记录,不受这个影响)
单项变量 = ("当前项", "下标")
失败策略 = {"fail": "整步失败(走「失败时」出口,记下是第几项、为什么)",
          "continue": "这一项结果留空(null),原因记进「失败项」,接着做下一项"}


class 做不了(Exception):
    """这一步做不下去。执行器把它换成节点失败(走「失败」出口或整条失败)。"""

    def __init__(self, code, 消息, 建议):
        self.code, self.消息, self.建议 = code, 消息, 建议
        super().__init__(f"{code}: {消息}")


def 配置问题(cfg):
    """返回 [(code, 消息, 建议, field_path)]。**只查这一步自己配置的形状**;
    迭代里面的步骤引用了什么、有没有套娃,由校验器看整张图再查(它要知道别的节点)。"""
    出 = []
    绑 = cfg.get("bindings") if isinstance(cfg.get("bindings"), dict) else {}
    if 绑 and "列表" not in 绑:
        出.append(("FOREACH_NO_INPUT", "还没选要逐项处理哪个列表", "在右侧「用到的数据」里给「列表」选一个前面步骤给的列表",
                  "config.bindings.列表"))
    for k in sorted(set(绑) - {"列表"}):
        出.append(("FOREACH_EXTRA_BINDING", f"「用到的数据」里多了一项「{k}」,列表迭代只用「列表」那一项,它不会被读",
                  f"删掉「{k}」;迭代里面的步骤要用它,就在那一步自己的「用到的数据」里选", f"config.bindings.{k}"))
    列 = 绑.get("列表")
    if 列 is not None and not (isinstance(列, dict) and "source" in 列):
        出.append(("FOREACH_NOT_REF", "「列表」是手写的,系统不知道它从哪来",
                  "在右侧「用到的数据」里给「列表」从下拉里选一个前面步骤给的列表", "config.bindings.列表"))
    elif isinstance(列, dict) and 列.get("source") == "constant" and not isinstance(列.get("value"), list):
        出.append(("FOREACH_NOT_LIST", "「列表」填的是一个固定值,而且它不是列表 —— 没有可以逐项做的东西",
                  "给「列表」选一个前面步骤给的列表", "config.bindings.列表"))
    上 = cfg.get("max_items")
    if 上 not in (None, "") and not (isinstance(上, int) and not isinstance(上, bool) and 1 <= 上 <= 技术上限):
        出.append(("FOREACH_MAX_RANGE", f"最多做几项要填 1 到 {技术上限} 之间的整数",
                  f"在右侧「基本」里改「最多做几项」。{技术上限} 是一步里能装下的运行记录的技术上限,不是业务建议;"
                  "要处理更多,先在前面用「列表操作」只取前几个,或者拆成几次运行", "config.max_items"))
    策 = cfg.get("item_failure_policy")
    if 策 not in (None, "") and 策 not in 失败策略:
        出.append(("FOREACH_BAD_POLICY", "「某一项失败时怎么办」系统不认识",
                  f"在右侧「基本」里重新选:{' / '.join(失败策略.values())}", "config.item_failure_policy"))
    o = cfg.get("item_output")
    if o not in (None, "", {}) and not (isinstance(o, dict) and o.get("source") == "node" and o.get("node_id")):
        出.append(("FOREACH_OUTPUT_NOT_INSIDE", "「每一项交出什么」要选迭代里面某一步的结果",
                  "在右侧「基本」里从下拉选迭代里面那一步的一项结果(比如 AI 处理 → text)", "config.item_output"))
    return 出


def 检查列表(值, cfg):
    """运行时进这一步先查:是不是列表、有没有超过上限。超了**一项都不做**(见文件头)。"""
    if not isinstance(值, list):
        raise 做不了("FOREACH_NOT_LIST", f"要逐项处理的不是列表,是{_类型名(值)}",
                  "在右侧「用到的数据」里核对「列表」的来源 —— 要选结果里是列表的那一项(比如 列表操作 → 结果)")
    上 = cfg.get("max_items")
    上 = 上 if isinstance(上, int) and not isinstance(上, bool) and 1 <= 上 <= 技术上限 else 技术上限
    if len(值) > 上:
        raise 做不了("FOREACH_TOO_MANY", f"给了 {len(值)} 项,超过这一步「最多做几项」的 {上} 项 —— 一项都没做",
                  "确认这次真要处理这么多:要的话把「最多做几项」调大(最多 "
                  f"{技术上限});不要的话在前面加「列表操作」只取前几个")


def _类型名(v):
    if v is None:
        return "空(null)"
    return {bool: "是 / 否", int: "数字", float: "数字", str: "文字", dict: "一条记录(对象)"}.get(type(v), type(v).__name__)


def 逐项记录(列表, 结果, 失败项):
    """这一步自己的运行记录:前 `记录里列几项` 项的输入 / 输出;多了**说清还有几项没列**(不悄悄只给一部分)。
    每一项里面每一步的输入输出另有记录(执行键 /迭代[第几项]),不受这个截断影响。"""
    坏 = {f["下标"]: f for f in 失败项}
    逐 = []
    for k in range(min(len(结果), 记录里列几项)):
        d = {"下标": k, "输入": 列表[k] if k < len(列表) else None}
        if k in 坏:
            d["失败"] = {x: 坏[k][x] for x in ("步骤", "code", "消息") if x in 坏[k]}
        else:
            d["输出"] = 结果[k]
        逐.append(d)
    出 = {"逐项": 逐}
    if len(结果) > 记录里列几项:
        出["没列出"] = (f"还有 {len(结果) - 记录里列几项} 项没列在这里(这里只列前 {记录里列几项} 项)—— "
                     "后面的不是没做:每一项里面每一步的输入输出在运行记录里按「第几项」分开记着")
    return 出


def 单项变量名(引用):
    """scope 引用取的是哪个单项变量(/当前项/金额 → 当前项)。不是 scope 引用 → None。"""
    if not isinstance(引用, dict) or 引用.get("source") != "scope":
        return None
    p = 引用.get("pointer")
    if p:
        return str(p).lstrip("/").split("/")[0].replace("~1", "/").replace("~0", "~")
    return 引用.get("field") or ""


def 所有引用(x):
    """把一个配置里所有结构化引用(带 source 的 dict)都找出来 —— 条件、赋值、绑定里都可能有。"""
    if isinstance(x, dict):
        if "source" in x and isinstance(x.get("source"), str):
            yield x
            return
        for v in x.values():
            yield from 所有引用(v)
    elif isinstance(x, list):
        for v in x:
            yield from 所有引用(v)
