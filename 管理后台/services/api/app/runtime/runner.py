#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workflow 执行器 —— **调度预设路径,不猜**(规格 §8、§16.1)。

## 三条在这个文件里必须成立的规矩

① **不从前端坐标推断先后**(§8)。下一步走哪儿,只看「这一步从哪个端口出去」
   和编译好的后继表。画布上谁在左边谁在右边,和执行顺序无关。

② **`skipped` 不是 `succeeded`**(§8)。条件分支没选中的那一路,它上面的节点
   状态是 `skipped`。这两个状态合并之后,「这次跑过了 8 个节点」这句话就没有意义了 ——
   而人正是拿这句话判断流程有没有按预期走。

③ **每个节点执行有唯一执行键**(§8):`(Run, node_id, 循环路径, 列表项, 尝试次数)`。
   **传输重试不改变逻辑副作用键** —— 网络重发一次不该变成第二次写入。

## 为什么执行器不碰数据库

它收两样东西:`适配器`(怎么调模型/检索/工具)和 `记事`(怎么记一条事件)。
两样都是函数。于是:

  · 夹具测试可以给一套**脚本化的 mock 响应**,不需要数据库也不需要模型;
  · Worker 把它们接到真表和真适配器上。

规格 §C.3 对脚本化模型响应的要求是「固定响应序列与 call_id……
**每轮清空响应游标**」—— 这个形状让那件事做得到。

## 「返回成功」和「任务达标」是两件事

`跑一张图()` 返回的 `执行状态` 只说流程按定义跑完了、确定性输出检查过了。
里面的事实对不对(总结是不是真的总结了那篇文章)**这里判不了**,
所以另有 `quality_evaluation_status`,默认是「未评」。§16.4 明写这两件事要分开存。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402
import compiler as CP  # noqa: E402

待执行, 执行中, 成功, 失败, 跳过 = "pending", "running", "succeeded", "failed", "skipped"


class 节点失败(Exception):
    def __init__(self, code, 消息, 建议):
        self.code, self.消息, self.建议 = code, 消息, 建议
        super().__init__(f"{code}: {消息}")


# ── 取值:结构化引用 → 真实值 ─────────────────────────────────────
def 取指针(obj, pointer):
    """JSON Pointer 的极简实现。**找不到返回 `DS.缺失`,不返回 None** ——
    「这个字段不存在」和「它的值是 null」在条件判断里处置相反(§3.3)。"""
    if not pointer or pointer == "/":
        return obj
    当前 = obj
    for 段 in pointer.lstrip("/").split("/"):
        段 = 段.replace("~1", "/").replace("~0", "~")
        if isinstance(当前, dict):
            if 段 not in 当前:
                return DS.缺失
            当前 = 当前[段]
        elif isinstance(当前, list):
            try:
                当前 = 当前[int(段)]
            except (ValueError, IndexError):
                return DS.缺失
        else:
            return DS.缺失
    return 当前


def 取值(引用, 状态):
    """按 `变量来源表` 取一个值。

    `状态` = dict(input=..., 节点={node_id: 输出}, system=..., scope=...)
    **密钥来源在这里直接拒绝** —— 执行器拿不到密钥,它只在连接层用。
    校验器已经拦过一次「把密钥绑进模型节点」,这里是第二道:
    一道靠校验、一道靠执行,两道都在,才不怕有人绕过校验直接提交定义。
    """
    src = 引用.get("source")
    来源 = DS.找来源(src)                      # 认不出当场抛
    if src == "constant":
        return 引用.get("value")
    if src == "input":
        return 取指针(状态.get("input"), 引用.get("pointer"))
    if src == "node":
        出 = 状态.get("节点", {})
        n = 引用.get("node_id")
        if n not in 出:
            # 到这儿说明那个节点没跑(被跳过了)。校验器本该拦住这种引用 ——
            # 能走到这里,要么定义是绕过校验提交的,要么校验器有漏。
            # **不返回 None**:返回 None 会让下游把它当成「值是空的」。
            return DS.缺失
        return 取指针(出[n], 引用.get("pointer"))
    if src == "scope":
        return 取指针(状态.get("scope"), 引用.get("pointer") or
                    ("/" + 引用["field"] if 引用.get("field") else None))
    if src == "system":
        return 取指针(状态.get("system"), 引用.get("pointer") or
                    ("/" + 引用["field"] if 引用.get("field") else None))
    if src == "secret":
        raise 节点失败("SECRET_IN_FLOW",
                     "定义里把密钥引用绑进了流程数据",
                     "密钥只能在连接层用(secret_ref)。"
                     "**执行器拿不到密钥** —— 这是第二道闸,校验器那道在前面")
    raise 节点失败("BIND_UNSUPPORTED", f"还不支持的变量来源 {来源['中文']}",
                 "换一种绑定方式")


def 解绑定(绑定, 状态, *, 允许缺失=()):
    """把一组绑定解成 {字段: 值}。**缺失的字段不填成 None,直接不出现** ——
    下游要靠「键在不在」区分「没有这个字段」和「值是 null」。"""
    出, 缺 = {}, []
    for 字段, 引用 in (绑定 or {}).items():
        v = 取值(引用, 状态)
        if v is DS.缺失:
            if 字段 not in 允许缺失:
                缺.append(字段)
            continue
        出[字段] = v
    return 出, 缺


# ── 白名单转换 ─────────────────────────────────────────────────────
def _转换一步(op, 入, 状态):
    名 = op["op"]
    if 名 == "pick":
        src = 取值(op["from"], 状态)
        if not isinstance(src, dict):
            raise 节点失败("TRANSFORM_TYPE", f"pick 要一个对象,拿到 {type(src).__name__}",
                         "先确认上游输出是对象")
        return {k: src[k] for k in op["fields"] if k in src}
    if 名 == "concat":
        块 = [取值(x, 状态) for x in op["parts"]]
        坏 = [b for b in 块 if not isinstance(b, str)]
        if 坏:
            raise 节点失败("TRANSFORM_TYPE",
                         f"concat 只拼字符串,里面有 {type(坏[0]).__name__}",
                         "**不做隐式类型转换** —— 数字要先过 to_string")
        return {op["into"]: "".join(块)}
    if 名 == "to_number":
        v = 取值(op["from"], 状态)
        try:
            n = float(v) if isinstance(v, str) and ("." in v or "e" in v.lower()) else int(v)
        except (TypeError, ValueError):
            raise 节点失败("TRANSFORM_NOT_NUMBER", f"{v!r} 转不成数字",
                         "**这是节点失败,不是静默给 0** —— "
                         "一个悄悄变成 0 的金额会一路算到账上")
        return {op["into"]: n}
    if 名 == "to_string":
        return {op["into"]: str(取值(op["from"], 状态))}
    if 名 == "join":
        v = 取值(op["from"], 状态)
        if not isinstance(v, list):
            raise 节点失败("TRANSFORM_TYPE", "join 要一个列表", "确认上游输出类型")
        return {op["into"]: op.get("sep", ",").join(str(x) for x in v)}
    if 名 == "length":
        v = 取值(op["from"], 状态)
        if not isinstance(v, (list, str, dict)):
            raise 节点失败("TRANSFORM_TYPE", "length 要列表/字符串/对象", "确认类型")
        return {op["into"]: len(v)}
    if 名 == "default":
        v = 取值(op["from"], 状态)
        return {op["into"]: op["value"] if v is DS.缺失 else v}
    if 名 == "merge_objects":
        出 = {}
        for x in op["parts"]:
            o = 取值(x, 状态)
            if not isinstance(o, dict):
                raise 节点失败("TRANSFORM_TYPE", "merge_objects 只合对象", "确认类型")
            撞 = set(出) & set(o)
            if 撞:
                raise 节点失败("TRANSFORM_KEY_CLASH", f"键冲突:{sorted(撞)}",
                             "**不静默后盖前** —— 被盖掉的那份数据不会有任何地方提到它")
            出.update(o)
        return 出
    raise 节点失败("TRANSFORM_UNKNOWN_OP", f"认不出的转换 {名!r}",
                 f"白名单:{sorted(CP.转换操作)}")


# ── 主循环 ─────────────────────────────────────────────────────────
def 跑一张图(计划, 输入, *, 适配器, 记事=None, run_id="run", 系统=None,
            上限=None):
    """按计划跑一遍。返回 dict(执行状态, 完成原因, 输出, 步骤, 用量)。

    `适配器` = {"llm": fn(节点配置, 编译后的输入) -> dict, "retrieve": ..., "tool": ...}
    `记事(种类, 载荷)` 每一步都会被调 —— Worker 拿它写 run_events。
    """
    记事 = 记事 or (lambda 种类, 载荷: None)
    系统 = 系统 or {}
    上限 = dict(上限 or {})
    状态 = {"input": 输入, "节点": {}, "system": 系统, "scope": {}}
    步骤, 用量 = [], {"模型调用": 0, "工具调用": 0}
    节点 = 计划["节点"]
    后继 = 计划["后继"]

    # 先把所有节点标成「待执行」。**跑完之后没被执行到的就是 skipped** ——
    # 这个初值让「哪些节点没跑」变成可以读出来的事实,而不是靠倒推。
    状态表 = {i: 待执行 for i in 节点}

    def 记一步(i, st, **kw):
        步 = dict(node_id=i, kind=节点[i]["type"], status=st,
                  # **唯一执行键**(§8)。现在没有循环和列表迭代,
                  # 路径段固定是 "/" 和 attempt=1 —— 但**键的形状现在就定下来**,
                  # 否则加循环的那天要改所有读这个键的地方。
                  execution_key=f"{run_id}:{i}:/:1", attempt=1, **kw)
        步骤.append(步)
        状态表[i] = st
        记事(f"node.{st}", 步)
        return 步

    当前 = 计划["入口"]
    完成原因, 执行状态, 输出 = None, "succeeded", {}
    while 当前:
        n = 节点[当前]
        t = n["type"]
        cfg = n.get("config") or {}
        记事("node.started", {"node_id": 当前, "kind": t})
        try:
            if t == "start":
                # **输入校验在这儿,在任何模型调用之前**(附录 C.2「输入缺失」那一行:
                # 「调用前拦截,**不消耗模型**」,判定方式是模型调用计数)。
                # 放到 LLM 节点里再查的话,第一次调用已经发出去了 ——
                # 而那次调用是要花钱的,还会在 Trace 上留下一条看起来正常的记录。
                need = set((cfg.get("input_schema") or {}).get("required") or [])
                缺入 = sorted(need - set((输入 or {})))
                if 缺入:
                    raise 节点失败("INPUT_MISSING", f"必填输入没给:{缺入}",
                                 "在试运行表单里把这些字段填上 —— "
                                 "**这次一个模型调用都没发出去**")
                状态["节点"][当前] = dict(输入)
                记一步(当前, 成功)
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else None
                continue

            if t in ("llm", "retrieve", "tool", "agent"):
                if t == "llm" and 上限.get("max_model_turns") is not None and \
                        用量["模型调用"] >= 上限["max_model_turns"]:
                    执行状态, 完成原因 = "incomplete", "max_turns"
                    记一步(当前, 失败, error_code="MAX_TURNS")
                    break
                实参, 缺 = 解绑定(cfg.get("bindings"), 状态)
                if 缺:
                    raise 节点失败("BIND_MISSING_AT_RUNTIME",
                                 f"运行时取不到这些绑定:{缺}",
                                 "这通常意味着上游那个节点**这一路没跑** —— "
                                 "校验器本该拦住(BIND_MAYBE_MISSING);"
                                 "如果它没拦,那是校验器的漏,请报出来")
                fn = 适配器.get(t)
                if fn is None:
                    raise 节点失败("ADAPTER_MISSING", f"没有 {t} 适配器",
                                 "**这不是「跑通了」** —— 缺适配器要报出来,"
                                 "不能当成这一步不需要做")
                r = fn(cfg, 实参)
                if t == "llm":
                    用量["模型调用"] += 1
                    # ⚠️ **普通 LLM 节点不执行它提出的工具调用**(§6.1、附录 C.2
                    # 「普通 LLM 请求工具」那一行:「不擅自执行,**明确类型处理**」)。
                    # 这是 Workflow 和 Agent 的分界线本身:
                    # 模型返回「我想调工具」在这里只是**一条记录**。
                    # 「明确类型处理」= 记一条事件让人看见,不是静默丢掉 ——
                    # 静默丢掉的话,「模型想调工具但没人理它」这件事没有任何地方说过,
                    # 而人会以为是模型不会用工具。
                    if r.get("tool_calls"):
                        记事("llm.tool_request_ignored", {
                            "node_id": 当前,
                            "请求了": [c.get("name") for c in r["tool_calls"]],
                            "为什么没执行":
                                "普通 LLM 节点不自动执行工具请求(§6.1)—— "
                                "要让模型真的用工具,换成 Agent 节点或显式的工具节点"})
                if t == "tool":
                    用量["工具调用"] += 1
                状态["节点"][当前] = r
                记一步(当前, 成功, execution_mode=r.get("execution_mode"))
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else None
                continue

            if t == "condition":
                选中 = None
                for b in cfg["branches"]:
                    左 = 取值(b["when"]["left"], 状态)
                    右 = 取值(b["when"]["right"], 状态) if "right" in b["when"] else None
                    try:
                        if DS.判(b["when"]["op"], 左,
                                 *([右] if "right" in b["when"] else [])):
                            选中 = b["key"]
                            break
                    except DS.变量缺失 as e:
                        # **缺变量按声明的缺失策略处理,不默默当 false**(§6.3)
                        策 = b.get("on_missing", "fail")
                        if 策 == "false":
                            continue
                        raise 节点失败("COND_VAR_MISSING", str(e),
                                     "在这条分支上声明 on_missing 策略,"
                                     "或者修掉那个绑定 —— "
                                     "**默认当 false 会把配置错误藏起来**")
                    except DS.类型不匹配 as e:
                        raise 节点失败("COND_TYPE", str(e), "插一个显式转换节点")
                键 = (DS.分支, 选中 if 选中 else "else")
                下 = 后继[当前].get(键, [])
                if not 下 and not 选中:
                    策 = cfg.get("else_policy")
                    if 策 in ("fail", "end"):
                        记一步(当前, 成功, branch_key="else")
                        执行状态 = "succeeded" if 策 == "end" else "incomplete"
                        完成原因 = None if 策 == "end" else "missing_evidence"
                        当前 = None
                        continue
                记一步(当前, 成功, branch_key=选中 or "else")
                状态["节点"][当前] = {"branch": 选中 or "else"}
                当前 = 下[0] if 下 else None
                continue

            if t == "merge":
                # **只取实际激活的那一路**(§6.1)。候选里那些被跳过的节点
                # 在 状态["节点"] 里根本没有键 —— 这正是「不填 None」的收益:
                # 「没跑」和「跑了但输出是 null」在这里必须分得开。
                值 = DS.缺失
                for c in cfg["candidates"]:
                    v = 取值(c, 状态)
                    if v is not DS.缺失:
                        值 = v
                        break
                if 值 is DS.缺失:
                    raise 节点失败("MERGE_NO_CANDIDATE",
                                 "汇合节点的候选里一个都没有值",
                                 "检查每条分支是不是都产出了那个字段;"
                                 "**这不是「值为空」,是一路都没跑成**")
                状态["节点"][当前] = {cfg["output_field"]: 值}
                记一步(当前, 成功)
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else None
                continue

            if t == "transform":
                出 = {}
                for op in cfg["operations"]:
                    出.update(_转换一步(op, 出, 状态))
                状态["节点"][当前] = 出
                记一步(当前, 成功)
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else None
                continue

            if t == "end":
                必需 = set((计划["输出Schema"].get("required") or []))
                输出, 缺 = 解绑定(cfg.get("bindings"), 状态)
                真缺 = sorted(必需 & set(缺))
                if 真缺:
                    raise 节点失败("END_OUTPUT_MISSING",
                                 f"必需输出字段取不到值:{真缺}",
                                 "**「跑完了」和「输出完整」是两件事** —— "
                                 "这次算 incomplete,不算成功")
                记一步(当前, 成功)
                当前 = None
                continue

            raise 节点失败("NODE_NOT_RUNNABLE", f"执行器还不支持 {t} 节点",
                         "换成已实现的节点;**未实现的节点不会被静默跳过**")

        except 节点失败 as e:
            记一步(当前, 失败, error_code=e.code, error_detail={"消息": e.消息,
                                                            "建议": e.建议})
            策 = (cfg.get("failure_policy") or "fail_run")
            错边 = 后继[当前].get((DS.失败, None), [])
            if 策 == "branch" and 错边:
                当前 = 错边[0]
                continue
            执行状态 = "failed"
            完成原因 = e.code
            当前 = None

    # 没被执行到的节点 = **跳过**,不是成功也不是失败(§8)
    for i, st in 状态表.items():
        if st == 待执行:
            步骤.append(dict(node_id=i, kind=节点[i]["type"], status=跳过,
                            execution_key=f"{run_id}:{i}:/:1", attempt=1,
                            skipped_reason="这条路径没被激活"))
    if 执行状态 == "succeeded" and 完成原因 is None and not 输出 and \
            (计划["输出Schema"].get("required") or []):
        执行状态, 完成原因 = "incomplete", "missing_evidence"

    return dict(
        执行状态=执行状态, 完成原因=完成原因, 输出=输出, 步骤=步骤, 用量=用量,
        逻辑哈希=计划["逻辑哈希"],
        # **另存一栏**:流程跑完了不代表里面的事实对(§16.4)
        quality_evaluation_status="未评",
        走过的路径=[s["node_id"] for s in 步骤 if s["status"] == 成功],
        跳过的节点=[s["node_id"] for s in 步骤 if s["status"] == 跳过],
    )
