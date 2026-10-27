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


class 需要等待(Exception):
    """这一步要等外面的事(人工核对 / 澜绣那边执行完回执),**整张图在这里挂起**。

    挂起不是失败,也不是成功:执行器把已完成节点的输出、用量、停在哪一步
    装进 `检查点` 交给调用方存库,然后**返回**(不占着 Worker 干等 —— §12.4)。
    等的那件事办完,调用方带着 `恢复=` 再调一次 `跑一张图`,从这一步接着走。

    > 一个挂在那里等人批的后台线程,等的是小时级 —— 那不是等待,那是泄漏。
    """

    def __init__(self, 种类, 载荷):
        self.种类, self.载荷 = 种类, 载荷
        super().__init__(f"等待 {种类}")


# 挂起时这一步和整次运行分别记成什么(和 contract/states.py 对齐)
等待态 = {"human": ("waiting_human", "waiting_approval"),
          "external": ("waiting_external", "waiting_external")}


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
        # 密钥只能在连接层用;执行器拿不到密钥 —— 这是第二道闸,校验器那道在前面
        raise 节点失败("SECRET_IN_FLOW",
                     "这一步「用到的数据」里选了密钥,流程里不能直接用密钥",
                     "在右侧「用到的数据」里换一个来源。接外部服务要用的密钥,请平台管理员配在「模型与连接」里")
    raise 节点失败("BIND_UNSUPPORTED", f"「{来源['中文']}」这种数据来源暂时还不能用",
                 "在右侧「用到的数据」里换一个来源")


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
            上限=None, 恢复=None, 样例=None):
    """按计划跑一遍。返回 dict(执行状态, 完成原因, 输出, 步骤, 用量)。

    `适配器` = {"llm": fn(节点配置, 编译后的输入) -> dict, "retrieve": ..., "tool": ...}
    `记事(种类, 载荷)` 每一步都会被调 —— Worker 拿它写 run_events。

    **挂起与恢复**:某一步抛 `需要等待`(人工节点总是;工具适配器在要等澜绣回执时),
    返回的 执行状态 是 waiting_approval / waiting_external,另带 `检查点`。
    `恢复` = 上次返回的检查点 + `结果`(等的那件事的结果)。恢复时:
      · 已完成节点的输出原样装回,**不重跑**(重跑会重复发消息 / 重复写入);
      · 停着的那一步直接拿 `结果` 当输出;`结果` 里带 `失败` 就按这一步失败处理;
      · 返回的 `步骤` 只含这一次新走的(停着的那一步会以成功再出现一次,同一个执行键)。
    """
    记事 = 记事 or (lambda 种类, 载荷: None)
    系统 = 系统 or {}
    上限 = dict(上限 or {})
    状态 = {"input": 输入, "节点": {}, "system": 系统, "scope": {}}
    步骤, 用量 = [], {"模型调用": 0, "工具调用": 0}
    节点 = 计划["节点"]
    # 选填的输入(10-24 经营报告:「那一期里的任意一天」不填 = 上一个完整的那一期):下游绑定它而它没给时
    # **不传这个参数**,不算缺失 —— 必填的照样在开始节点那道拦。从图里的开始节点现算,不靠走过开始节点:
    # 挂起再恢复时开始节点不重跑,靠它记的话恢复之后就丢了
    for _n in 节点.values() if isinstance(节点, dict) else 节点:
        _c = (_n.get("config") or {}) if isinstance(_n, dict) else {}
        if isinstance(_n, dict) and _n.get("type") == "start":
            _sch = _c.get("input_schema") or {}
            状态["选填输入"] = sorted(set(_sch.get("properties") or {}) - set(_sch.get("required") or []))
    后继 = 计划["后继"]

    # 先把所有节点标成「待执行」。**跑完之后没被执行到的就是 skipped** ——
    # 这个初值让「哪些节点没跑」变成可以读出来的事实,而不是靠倒推。
    状态表 = {i: 待执行 for i in 节点}
    注入 = {}
    # 正在跑的循环(10-27):[{循环, 第几轮, 状态}]。**进检查点、恢复不清零**(§6.3)—— 停在循环里等人核对,
    # 回来接着是同一轮;清零的计数等于没有上限。现在只支持一层(嵌套循环校验器拦)
    帧们 = []

    def 路径():
        return "".join(f"/{f['循环']}[{f['第几轮']}]" for f in 帧们) or "/"

    def 循环回(i):
        """i 是循环体里的一步、而且它后面没有下一步 → 这一轮做完,回到循环本身判下一轮;否则 None(整条流程到头)。"""
        c = 节点[i].get("container") if i in 节点 else None
        return c if c and 帧们 and 帧们[-1]["循环"] == c else None
    if 恢复:
        if 恢复.get("逻辑哈希") and 恢复["逻辑哈希"] != 计划["逻辑哈希"]:
            # **检查点是对着哪一版图存的,就只能拿那一版接着跑** —— 换了图,
            # 「已完成节点的输出」可能对不上新图里的任何一个节点
            raise ValueError("检查点的逻辑哈希和这份计划对不上 —— 恢复要用挂起时那一版定义")
        if 恢复["从"] not in 节点:
            raise ValueError(f"检查点停在 {恢复['从']},这份计划里没有这个节点")
        状态["节点"] = dict(恢复.get("节点输出") or {})
        用量 = dict(恢复.get("用量") or 用量)
        for i, st in (恢复.get("已完成") or {}).items():
            if i in 状态表:
                状态表[i] = st
        注入[恢复["从"]] = 恢复.get("结果") or {}
        帧们[:] = [dict(f) for f in (恢复.get("循环帧") or [])]
        if 帧们:
            状态["scope"] = 帧们[-1]["状态"]

    def 记一步(i, st, *, 入=None, 出=None, **kw):
        步 = dict(node_id=i, kind=节点[i]["type"], status=st,
                  # **唯一执行键**(§8)。现在没有循环和列表迭代,
                  # 路径段固定是 "/" 和 attempt=1 —— 但**键的形状现在就定下来**,
                  # 否则加循环的那天要改所有读这个键的地方。
                  execution_key=f"{run_id}:{i}:{路径()}:1", attempt=1, **kw)
        # 这一步实际收到的 / 交出的(用户 10-26 拍「记录每一步的输入输出」,方案 §8.3「节点记录」那一层)。
        # ⚠️ **只放进步骤,不放进事件载荷** —— 运行详情把事件原样返回、不按授权打码,
        # 放进去等于让没有「查看敏感输入」授权的人也读到客户原文。None = 这一步没有这一侧,不是「值为空」
        if 入 is not None:
            步["input"] = 入
        if 出 is not None:
            步["output"] = 出
        步骤.append(步)
        状态表[i] = st
        记事(f"node.{st}", {k: v for k, v in 步.items() if k not in ("input", "output")})
        return 步

    当前 = 恢复["从"] if 恢复 else 计划["入口"]
    完成原因, 执行状态, 输出 = None, "succeeded", {}
    检查点 = None

    def _拿注入(i):
        """恢复时停着的那一步:结果带 `失败` 就当这一步失败,否则它就是这一步的输出。"""
        r = 注入.pop(i)
        if r.get("失败"):
            f = r["失败"]
            raise 节点失败(f.get("code") or "EXTERNAL_FAILED", f.get("消息") or "外部那一步没办成",
                         f.get("建议") or "看这一步的详情")
        return r

    while 当前:
        n = 节点[当前]
        t = n["type"]
        cfg = n.get("config") or {}
        本步入 = None          # 这一步解出来的入参 —— 挂起 / 失败时也要记得它收到了什么
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
                    raise 节点失败("INPUT_MISSING", f"还有必填的内容没填:{'、'.join(缺入)}",
                                 "把这几项填上再跑。这次一个模型都没调用,不花钱")
                状态["节点"][当前] = dict(输入)
                记一步(当前, 成功, 入=dict(输入 or {}), 出=dict(输入))
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue

            if 样例 is not None and t in ("llm", "retrieve", "tool", "agent", "human"):
                # 样例预览(10-26,方案 §8.1;用户拍「照你的建议走」):**模型、检索、业务动作、人工核对都不真做**,
                # 直接拿这一步上次成功的输出 —— 不花钱、不写入、不用等人。条件 / 转换 / 汇合照常跑:
                # 预览要验的正是「刚改了结构,流程还接得通不通」。没有样例就停在这一步说清,不编一个结果
                if 当前 not in 样例:
                    raise 节点失败("NO_SAMPLE_OUTPUT", "这一步还没有样例:它从来没有成功跑过",
                                 "先用「正常」或「连接测试」把这条流程跑通一次,再用样例预览")
                状态["节点"][当前] = dict(样例[当前])
                记一步(当前, 成功, 出=状态["节点"][当前])
                记事("node.sample_used", {"node_id": 当前, "说明": "样例预览:用的是这一步上次成功的输出,没有真调"})
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue
            if t == "human":
                if 当前 in 注入:
                    状态["节点"][当前] = _拿注入(当前)
                    记一步(当前, 成功, branch_key=状态["节点"][当前].get("决定"), 出=状态["节点"][当前])
                    下 = 后继[当前].get((DS.成功, None), [])
                    当前 = 下[0] if 下 else 循环回(当前)
                    continue
                载荷, 缺 = 解绑定(cfg.get("payload_binding"), 状态)
                本步入 = 载荷
                if 缺:
                    raise 节点失败("BIND_MISSING_AT_RUNTIME", f"要给核对人看的材料取不到:{'、'.join(缺)}",
                                 "前面产出这些材料的那一步这次没跑到;在右侧「用到的数据」里核对一下来源")
                raise 需要等待("human", {
                    "node_id": 当前, "request_kind": cfg.get("request_kind"),
                    "candidate_roles": cfg.get("candidate_roles") or [],
                    "allowed_fields": cfg.get("allowed_fields") or [],
                    "expires_at_policy": cfg.get("expires_at_policy"), "材料": 载荷})

            if t in ("llm", "retrieve", "tool", "agent"):
                if 当前 in 注入:
                    r = _拿注入(当前)
                    if t == "tool":
                        用量["工具调用"] += 1
                    状态["节点"][当前] = r
                    记一步(当前, 成功, execution_mode=r.get("execution_mode"), 出=r)
                    下 = 后继[当前].get((DS.成功, None), [])
                    当前 = 下[0] if 下 else 循环回(当前)
                    continue
                if t == "llm" and 上限.get("max_model_turns") is not None and \
                        用量["模型调用"] >= 上限["max_model_turns"]:
                    执行状态, 完成原因 = "incomplete", "max_turns"
                    记一步(当前, 失败, error_code="MAX_TURNS")
                    break
                选填 = set(状态.get("选填输入") or ())
                实参, 缺 = 解绑定(cfg.get("bindings"), 状态, 允许缺失=[
                    字段 for 字段, 引 in (cfg.get("bindings") or {}).items()
                    if isinstance(引, dict) and 引.get("source") == "input"
                    and str(引.get("pointer") or "").lstrip("/") in 选填])
                本步入 = 实参
                if 缺:
                    # 通常是上游那一步这一路没跑 —— 校验器本该拦住(BIND_MAYBE_MISSING);走到这里说明校验器漏了
                    raise 节点失败("BIND_MISSING_AT_RUNTIME",
                                 f"这一步要用的数据取不到:{'、'.join(缺)}",
                                 "产出这些数据的那一步这次没跑到(多半是走了另一条分支)。"
                                 "在分支之后加一个「分支汇合」再取;检查配置没提示这个问题的话,请告诉技术管理员")
                fn = 适配器.get(t)
                if fn is None:
                    # 缺适配器要报出来,不能当成这一步不需要做
                    raise 节点失败("ADAPTER_MISSING", "这类步骤在当前环境还跑不了",
                                 "请联系技术管理员 —— 这一步没有执行,不是执行成功")
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
                记一步(当前, 成功, execution_mode=r.get("execution_mode"), 入=实参, 出=r)
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue

            if t == "condition":
                选中 = None
                本步入 = []    # 每一路拿什么跟什么比 —— 「为什么走了这一路」要看得见
                for b in cfg["branches"]:
                    # 一路可以有几条条件,用「且 / 或」连(10-27 照 Dify;用户拍把一串「填了 X 吗」合成一个节点)。
                    # 老定义只有一条 `when` —— 当成只有一条的列表,意思不变
                    条们, 连 = DS.分支条件(b)
                    if not 条们:
                        # 一条条件都没有:按「且」算会**永远满足**(没有哪条不满足)—— 不许,校验器那道在前面
                        raise 节点失败("COND_EMPTY", f"「{b.get('key')}」这一路一条条件都没有",
                                     "在右侧「基本」里给这一路至少加一条条件,用不上就删掉这一路")
                    满足 = 连 == "and"
                    for 序, w in enumerate(条们, 1):
                        左 = 取值(w["left"], 状态)
                        右 = 取值(w["right"], 状态) if "right" in w else None
                        本步入.append({"这一路": b["key"], **({"第几条": 序, "连接": "且" if 连 == "and" else "或"} if len(条们) > 1 else {}),
                                     "比较": w.get("op"), "左边": None if 左 is DS.缺失 else 左,
                                     **({"右边": None if 右 is DS.缺失 else 右} if "right" in w else {})})
                        try:
                            真 = DS.判(w["op"], 左, *([右] if "right" in w else []))
                        except DS.变量缺失 as e:
                            # **缺变量按声明的缺失策略处理,不默默当 false**(§6.3);每条自己声明,老写法挂在这一路上
                            if (w.get("on_missing") or b.get("on_missing") or "fail") == "false":
                                真 = False
                            else:
                                # 默认当「不满足」会把配置错误藏起来,所以缺值就停
                                raise 节点失败("COND_VAR_MISSING", f"「{b.get('key')}」这一路的条件要用的数据没有值",
                                             "检查这一路条件里比较的数据从哪来;那一项本来就可能没有的话,告诉技术管理员把它设成「缺值按不满足算」")
                        except DS.类型不匹配 as e:
                            raise 节点失败("COND_TYPE", f"「{b.get('key')}」这一路的条件比较的两边类型对不上(比如拿文字跟数字比)",
                                         "在条件前面加一个「字段转换」把类型转成一样的")
                        # 短路(和 Dify 一样):「且」碰到一条不满足就定了,「或」碰到一条满足就定了 —— 后面的不再取值
                        if 连 == "and" and not 真:
                            满足 = False
                            break
                        if 连 == "or" and 真:
                            满足 = True
                            break
                    if 满足:
                        选中 = b["key"]
                        break
                键 = (DS.分支, 选中 if 选中 else "else")
                下 = 后继[当前].get(键, [])
                if not 下 and not 选中:
                    策 = cfg.get("else_policy")
                    if 策 in ("fail", "end"):
                        记一步(当前, 成功, branch_key="else", 入=本步入, 出={"branch": "else"})
                        执行状态 = "succeeded" if 策 == "end" else "incomplete"
                        完成原因 = None if 策 == "end" else "missing_evidence"
                        当前 = None
                        continue
                状态["节点"][当前] = {"branch": 选中 or "else"}
                记一步(当前, 成功, branch_key=选中 or "else", 入=本步入, 出=状态["节点"][当前])
                当前 = 下[0] if 下 else 循环回(当前)
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
                    # 这不是「值为空」,是一路都没跑成
                    raise 节点失败("MERGE_NO_CANDIDATE",
                                 "要汇合的几路一个都没有结果",
                                 "检查每条分支是不是都产出了要汇合的那一项")
                状态["节点"][当前] = {cfg["output_field"]: 值}
                记一步(当前, 成功, 出=状态["节点"][当前])
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue

            if t == "transform":
                出 = {}
                for op in cfg["operations"]:
                    出.update(_转换一步(op, 出, 状态))
                状态["节点"][当前] = 出
                记一步(当前, 成功, 出=出)
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue

            if t == "answer":
                # 直接回复(10-27):模板里每个名字取「用到的数据」里同名那一项。**缺一项就失败,不回半句** ——
                # 「您的订单{{单号}}已…」带着花括号发给顾客,比这一步失败糟得多
                模板 = cfg.get("template") or ""
                值, 缺 = 解绑定(cfg.get("bindings"), 状态)
                本步入 = 值
                缺 = sorted(set(缺) | (set(DS.回复占位名(模板)) - set(值) - set(缺)))
                if 缺:
                    raise 节点失败("ANSWER_VALUE_MISSING", f"回复里要填的内容取不到:{'、'.join(缺)}",
                                 "在右侧「用到的数据」里给这几项选来源;来源那一步这次没跑到的话,加「分支汇合」")
                if not 模板.strip():
                    raise 节点失败("ANSWER_EMPTY", "这一步没写要回复什么", "在右侧「基本」里写回复内容")
                状态["节点"][当前] = {"回复": DS.填回复(模板, 值)}
                记一步(当前, 成功, 入=值, 出=状态["节点"][当前])
                下 = 后继[当前].get((DS.成功, None), [])
                当前 = 下[0] if 下 else 循环回(当前)
                continue

            if t == "loop":
                # 有界循环(10-27;用户拍经营报告「核对不过最多重写 3 次」)。**先判断后执行**:每一轮开始前
                # 拿循环状态判条件,不满足就从「循环出」出去;满足就进循环体。循环体里走到头(或连回循环本身)= 这一轮做完,
                # 按 loop_state 的 update 从这一轮的结果更新状态,再回到这里判下一轮
                上 = int(cfg.get("max_iterations") or 0)
                if not 帧们 or 帧们[-1]["循环"] != 当前:
                    初 = {k: (v.get("initial") if isinstance(v, dict) else None)
                          for k, v in (cfg.get("loop_state") or {}).items()}
                    帧们.append({"循环": 当前, "第几轮": 0, "状态": 初})
                else:
                    帧 = 帧们[-1]
                    for k, v in (cfg.get("loop_state") or {}).items():
                        u = v.get("update") if isinstance(v, dict) else None
                        if u:
                            新 = 取值(u, 状态)
                            if 新 is not DS.缺失:          # 这一轮没走到那一步 → 状态不变,不填成 None
                                帧["状态"][k] = 新
                帧 = 帧们[-1]
                状态["scope"] = 帧["状态"]
                条们, 连 = DS.分支条件(cfg["condition"] if "conditions" in (cfg.get("condition") or {})
                                       else {"when": cfg.get("condition")})
                判们 = []
                for w in 条们:
                    try:
                        判们.append(bool(DS.判(w["op"], 取值(w["left"], 状态),
                                               *([取值(w["right"], 状态)] if "right" in w else []))))
                    except DS.变量缺失:
                        判们.append(False)        # 循环状态还没有那一项 = 不满足,不进下一轮(不会因为缺值多跑一轮)
                继续 = (all(判们) if 连 == "and" else any(判们)) if 判们 else False
                if 继续 and 帧["第几轮"] >= 上:
                    # 到上限还没达标:**受限停止**,不是成功(§6.1)—— 和模型轮数到上限同一种说法
                    记一步(当前, 失败, error_code="MAX_ITERATIONS", 出={"轮数": 帧["第几轮"], "状态": 帧["状态"]},
                           error_detail={"消息": f"循环跑满 {上} 轮还没做完", "建议": "看最后一轮停在哪;要再试就重新发起"})
                    执行状态, 完成原因 = "incomplete", "max_iterations"
                    帧们.pop()
                    状态["scope"] = 帧们[-1]["状态"] if 帧们 else {}
                    break
                if not 继续:
                    帧们.pop()
                    状态["scope"] = 帧们[-1]["状态"] if 帧们 else {}
                    状态["节点"][当前] = {"轮数": 帧["第几轮"], **帧["状态"]}
                    记一步(当前, 成功, 出=状态["节点"][当前])
                    下 = 后继[当前].get((DS.循环出, None), [])
                    当前 = 下[0] if 下 else 循环回(当前)
                    continue
                帧["第几轮"] += 1
                # 新的一轮:循环体里上一轮的结果清掉 —— 这一轮引用的必须是这一轮跑出来的(没跑到就是取不到,不拿上一轮的冒充)
                for i2, n2 in 节点.items():
                    if n2.get("container") == 当前:
                        状态["节点"].pop(i2, None)
                记事("loop.iteration", {"node_id": 当前, "第几轮": 帧["第几轮"]})
                下 = 后继[当前].get((DS.循环体, None), [])
                if not 下:
                    raise 节点失败("SCOPE_NO_ENTRY", "循环里面的步骤没有连上", "从循环连一条线到循环里的第一步")
                当前 = 下[0]
                continue

            if t == "end":
                必需 = set((计划["输出Schema"].get("required") or []))
                输出, 缺 = 解绑定(cfg.get("bindings"), 状态)
                真缺 = sorted(必需 & set(缺))
                if 真缺:
                    # 「跑完了」和「输出完整」是两件事
                    raise 节点失败("END_OUTPUT_MISSING",
                                 f"最后要返回的内容缺了:{'、'.join(真缺)}",
                                 "在「结束」的「用到的数据」里核对这几项从哪来;来源那一步这次没跑到的话,加「分支汇合」")
                记一步(当前, 成功, 出=输出)
                当前 = None
                continue

            # 未实现的节点不会被静默跳过
            raise 节点失败("NODE_NOT_RUNNABLE", "这类步骤还不能运行",
                         "换成能用的步骤搭出同样的流程")

        except 需要等待 as w:
            步态, 执行状态 = 等待态[w.种类]
            记一步(当前, 步态, waiting_for=w.种类, 入=本步入)
            检查点 = {"从": 当前, "逻辑哈希": 计划["逻辑哈希"], "节点输出": 状态["节点"], "循环帧": 帧们,
                      "用量": 用量, "已完成": {i: st for i, st in 状态表.items()
                                               if st not in (待执行, 步态)},
                      "等待": {"种类": w.种类, "node_id": 当前, "载荷": w.载荷}}
            当前 = None
            break

        except 节点失败 as e:
            记一步(当前, 失败, error_code=e.code, error_detail={"消息": e.消息,
                                                            "建议": e.建议}, 入=本步入)
            策 = (cfg.get("failure_policy") or "fail_run")
            错边 = 后继[当前].get((DS.失败, None), [])
            if 策 == "branch" and 错边:
                当前 = 错边[0]
                continue
            执行状态 = "failed"
            完成原因 = e.code
            当前 = None

    if 检查点:
        # **挂起时不算跳过** —— 后面的节点还没轮到,不是「这条路径没被激活」
        return dict(执行状态=执行状态, 完成原因=None, 输出={}, 步骤=步骤, 用量=用量,
                    逻辑哈希=计划["逻辑哈希"], quality_evaluation_status="未评",
                    走过的路径=[s["node_id"] for s in 步骤 if s["status"] == 成功],
                    跳过的节点=[], 检查点=检查点)

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
