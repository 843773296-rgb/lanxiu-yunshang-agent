#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定义校验器 —— **服务端权威的图校验**(规格 §7.2、§17.1、附录 A-1)。

## 这个校验器最核心的一条:变量可用性靠**支配关系**判,不靠找字符串

规格附录 A-1 说得很具体:「数据流分析检查**每条可达路径**是否提供必需变量,
条件分支通过显式汇合消除不确定来源」,而 §7.2 结尾补了一句禁令:
「**不能仅检查字符串里有没有出现某个变量名**」。

那句禁令在防什么:最省事的实现是「这张图里有没有一个 id 叫 summarize 的节点?
有 → 那么引用 summarize 的输出就是合法的」。这个判据放过的是最常见的一种坏图 ——

    开始 → 判断语言 → ┬─ 中文分支 ─→ 直接总结 ─┐
                      └─ 英文分支 ─→ 翻译 → 总结 ─┴→ 报告(读「翻译」的输出)

「翻译」这个节点**存在**,但中文输入那一路根本不会跑到它。
按名字找的校验器说「合法」;跑中文样例的时候,报告节点读到一个不存在的字段。
而这件事在画布上**看起来完全正常**:两条线都连着,节点都在。

正确的判据在图论里有名字:**支配关系(dominator)**。
「m 支配 n」= 从开始走到 n 的**每一条路径都必经 m**。于是:

  · 「引用了尚未生成的变量」 = m 不支配 n
  · 「只在某一分支有值的变量被所有路径必填使用」 = **同一个判据**

两个听起来不一样的错法是一个式子:`dom(n) = {n} ∪ ⋂(每个前驱的 dom)`。
而规格说的「条件分支通过**显式汇合**消除不确定来源」正好落在这上面:
汇合节点本身是支配者(所有分支都汇到它),所以**经汇合取值合法,跨分支直接取值不合法**。

> 一个能说清「为什么这个引用不安全」的校验器,和一个只会说「配置有误」的校验器,
> 差别不在准确率,在**人看完报告之后知不知道该改哪儿**。

## 为什么报告里每条都要带 node_id / field_path / 建议

规格 §17.1:报告要「包含 **node_id/field_path/阻断级别**」。§5.2 举了个例子说
错误内容要可修复:「报告节点读取了**只在英文分支生成**的变量」。
一句「图校验失败」会让人去重连线、去改 Schema、去怀疑后端 —— 它把定位成本
全推给了读报告的人。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402

阻断 = "blocking"     # 不修不许冻结版本
警告 = "warning"      # 可以冻结,但要显示


def 问(级别, code, 消息, 建议, *, node_id=None, field_path=None, edge=None):
    """一条校验问题。`建议` 必填 —— 和 contract/errors.py 同一条规矩:
    写不出建议的问题说明还没搞清它到底错在哪。"""
    if not (建议 or "").strip():
        raise ValueError(f"{code} 没写「怎么改」—— 一条定位不到动作的校验问题,"
                         f"和一句「配置有误」是一回事")
    return dict(级别=级别, code=code, 消息=消息, 建议=建议,
                node_id=node_id, field_path=field_path, edge=edge)


# ── 作用域 ─────────────────────────────────────────────────────────
# 节点可以挂在一个容器里(循环 / 迭代 / 并行的子图)。`container` 指向那个容器节点。
# **跨容器引用局部变量是非法的**(§7.2):出了作用域那个值就不存在,
# 而引用它的表达式在画布上看起来和别的引用一模一样。
def _作用域(节点们):
    """返回 {容器id 或 None: [该作用域里的节点]},以及 {node_id: 容器id}。"""
    按域, 属于 = {}, {}
    for n in 节点们:
        c = n.get("container")
        按域.setdefault(c, []).append(n)
        属于[n.get("id")] = c
    return 按域, 属于


def _祖先域(容器id, 属于):
    """一个作用域能看见的所有上层作用域(含自己)。"""
    出, 当前 = [], 容器id
    见过 = set()
    while True:
        出.append(当前)
        if 当前 is None or 当前 in 见过:
            break
        见过.add(当前)
        当前 = 属于.get(当前)
    return 出


# ── 可达性与支配关系 ───────────────────────────────────────────────
def _可达(入口, 后继):
    见, 栈 = set(), [入口] if 入口 else []
    while 栈:
        x = 栈.pop()
        if x in 见:
            continue
        见.add(x)
        栈.extend(后继.get(x, ()))
    return 见


def 支配集(入口, 后继, 可达集):
    """`dom[n]` = 从入口到 n 的每条路径都必经的节点集合(含 n 自己)。

    标准的迭代不动点算法。图里有环也收敛(交集只会变小),
    所以**循环容器内部的子图也能用它** —— 不需要先证明它是 DAG。
    """
    前驱 = {n: set() for n in 可达集}
    for a in 可达集:
        for b in 后继.get(a, ()):
            if b in 可达集:
                前驱[b].add(a)
    dom = {n: set(可达集) for n in 可达集}
    if 入口 in dom:
        dom[入口] = {入口}
    变了 = True
    while 变了:
        变了 = False
        for n in 可达集:
            if n == 入口:
                continue
            ps = [dom[p] for p in 前驱[n] if p in dom]
            新 = ({n} | set.intersection(*ps)) if ps else {n}
            if 新 != dom[n]:
                dom[n] = 新
                变了 = True
    return dom


def _找环(入口, 后继, 可达集):
    """返回一条环(节点列表),没有环就返回 None。"""
    白, 灰, 黑 = 0, 1, 2
    色 = {n: 白 for n in 可达集}
    路 = []

    def 走(n):
        色[n] = 灰
        路.append(n)
        for m in 后继.get(n, ()):
            if m not in 色:
                continue
            if 色[m] == 灰:
                return 路[路.index(m):] + [m]
            if 色[m] == 白:
                r = 走(m)
                if r:
                    return r
        路.pop()
        色[n] = 黑
        return None

    if 入口 in 色:
        return 走(入口)
    return None


# ── 主入口 ─────────────────────────────────────────────────────────
def 校验(定义, *, 依赖存在=None, 父额度=None):
    """返回问题清单(空清单 = 没有阻断也没有警告)。

    `依赖存在(种类, id) -> bool` 由调用方给:校验器**不自己查数据库** ——
    它要能在没有数据库的情况下跑(夹具测试、前端同源校验)。
    给了就查引用存不存在;不给就跳过那一类检查,**并且在报告里说自己跳过了**
    (§C.4:「缺凭证或只测接口不能写整件事通过」)。
    """
    出 = []

    # ① 骨架:定义本身的形状 ────────────────────────────────────────
    if not isinstance(定义, dict):
        return [问(阻断, "DEF_NOT_OBJECT", "定义不是一个对象",
                  "检查提交的 JSON 顶层是不是 {} 而不是数组或字符串")]
    节点们 = 定义.get("nodes")
    边们 = 定义.get("edges")
    if not isinstance(节点们, list) or not 节点们:
        出.append(问(阻断, "DEF_NO_NODES", "定义里没有 nodes",
                   "至少要有一个「开始」和一个「结束」节点"))
        return 出
    if not isinstance(边们, list):
        边们 = []
        出.append(问(阻断, "DEF_NO_EDGES", "定义里没有 edges 数组",
                   "空图也要给一个空数组 —— 缺这个键和「一条边都没有」不是一回事"))

    # 重复 ID:**先查这条**。后面所有按 id 查节点的逻辑都建立在 id 唯一上,
    # 重复的话「按 id 找到的那个」是哪一个取决于遍历顺序 —— 而那不是确定语义。
    见过, 重复 = set(), []
    for n in 节点们:
        i = n.get("id")
        if not i:
            出.append(问(阻断, "NODE_NO_ID", "有个节点没有 id",
                       "每个节点要一个稳定 id;**它不随名称改变**(§5.2)"))
            continue
        if i in 见过:
            重复.append(i)
        见过.add(i)
    for i in sorted(set(重复)):
        出.append(问(阻断, "NODE_DUP_ID", f"节点 id 重复:{i}",
                   "改成不同的稳定 id。复制节点要生成新 id,"
                   "**并且检查哪些输入还引用着原节点**(§5.2)", node_id=i))
    按id = {n.get("id"): n for n in 节点们 if n.get("id")}

    # 未知节点类型 / 未实现的节点
    for n in 节点们:
        t, i = n.get("type"), n.get("id")
        try:
            元 = DS.找节点(t)
        except KeyError:
            出.append(问(阻断, "NODE_UNKNOWN_TYPE", f"认不出的节点类型:{t!r}",
                       f"节点类型只能是登记过的那些:"
                       f"{[x['名'] for x in DS.节点表]}", node_id=i))
            continue
        if 元["实现"] == DS.未实现:
            # **不摆空按钮冒充可用**(§6.1)。这条是阻断:一张用了未实现节点的图
            # 能冻结、能发布,然后在运行时才发现跑不了 —— 那比现在拦住贵得多。
            出.append(问(阻断, "NODE_NOT_IMPLEMENTED",
                       f"「{元['中文']}」节点还没实现",
                       f"先用已实现的节点搭出闭环;"
                       f"已实现的有:{[x['中文'] for x in DS.可用节点()]}",
                       node_id=i))
        # 必填配置
        cfg = n.get("config") or {}
        for f in 元["必填"]:
            if f not in cfg or cfg[f] in (None, "", [], {}):
                出.append(问(阻断, "NODE_MISSING_CONFIG",
                           f"「{元['中文']}」缺必填配置 {f}",
                           f"在右侧面板把 {f} 填上", node_id=i, field_path=f"config.{f}"))
        # **自由字段一律拒绝**(§16.5:节点 Schema 由契约注册表声明)。
        #
        # ⚠️ 判据要把「没登记的字段」和「登记了但对这个节点不适用的通用字段」分开 ——
        # 第一版没分,于是开始节点上那个假的 `timeout_seconds` 被报了**两条**:
        # 「没登记的配置字段」+「不该有这个设置」。同一个字段两条不同的错,
        # 人会以为是两个问题,去修第一条,改完还是红,然后开始怀疑校验器。
        # **一个会多报的校验器,会训练人跳过校验。**
        # 这条是「集合相等」那个判据抓到的 —— 「至少报了一条」永远抓不到多报。
        # 通用字段**整批交给下面那条「不适用」检查管** —— 不在这里重复报一次。
        # 标了不适用的会在那里报 NODE_INAPPLICABLE_FIELD(消息说的是
        # 「这个设置填了不生效」,那才是人要知道的事);没标不适用的就是合法的。
        野 = [k for k in cfg
              if k not in 元["配置"] and k not in DS._通用名]
        for k in 野:
            出.append(问(阻断, "NODE_UNKNOWN_CONFIG",
                       f"「{元['中文']}」上有个没登记的配置字段 {k}",
                       f"这个节点登记过的配置字段是 {元['配置']} —— "
                       f"**没登记的字段不会有任何地方读它**,填了不算",
                       node_id=i, field_path=f"config.{k}"))
        # 通用字段里标了「不适用」的,不许出现在配置里(§6:不许有拧了不算数的设置)
        for k in 元["不适用"]:
            if k in cfg:
                出.append(问(阻断, "NODE_INAPPLICABLE_FIELD",
                           f"「{元['中文']}」不该有 {k} 这个设置",
                           f"这个节点{'不发起会超时的外部调用' if k in ('timeout_seconds', 'retryable_errors', 'max_retries') else '用不上这一项'},"
                           f"**这个设置填了不生效** —— 界面上该隐藏它",
                           node_id=i, field_path=f"config.{k}"))

    # 开始 / 结束
    开始们 = [n["id"] for n in 节点们 if n.get("type") == "start" and n.get("id")]
    结束们 = [n["id"] for n in 节点们 if n.get("type") == "end" and n.get("id")]
    if not 开始们:
        出.append(问(阻断, "GRAPH_NO_START", "没有「开始」节点",
                   "加一个「开始」节点,并在它上面声明输入 Schema"))
    if len(开始们) > 1:
        出.append(问(阻断, "GRAPH_MULTI_START",
                   f"有 {len(开始们)} 个「开始」节点:{开始们}",
                   "每个顶层 Workflow **只能有一个**开始(§6.1)—— "
                   "两个入口的话「执行从哪儿开始」不是确定的"))
    if not 结束们:
        出.append(问(阻断, "GRAPH_NO_END", "没有「结束」节点",
                   "加一个「结束」节点并把输出字段映射上去"))

    # ② 连线 ────────────────────────────────────────────────────────
    按域, 属于 = _作用域(节点们)
    后继 = {i: [] for i in 按id}
    for e in 边们:
        a, b, p = e.get("source"), e.get("target"), e.get("port")
        标 = f"{a} --{p}--> {b}"
        if a not in 按id or b not in 按id:
            出.append(问(阻断, "EDGE_DANGLING", f"悬空连线:{标}",
                       "连线两端都要指向存在的节点;删掉它或者补上那个节点", edge=标))
            continue
        元a = DS.找节点(按id[a]["type"]) if 按id[a].get("type") in \
            {x["名"] for x in DS.节点表} else None
        if 元a and p not in 元a["端口"]:
            出.append(问(阻断, "EDGE_UNKNOWN_PORT",
                       f"「{元a['中文']}」没有 {p!r} 这个出端口",
                       f"它的出端口是 {元a['端口']}", node_id=a, edge=标))
            continue
        # 跨作用域连线:只允许容器 → 它自己的子图(循环体),或同一作用域内
        域a, 域b = 属于.get(a), 属于.get(b)
        if 域a != 域b and not (域b == a) and not (域a == b):
            出.append(问(阻断, "EDGE_CROSS_SCOPE",
                       f"连线跨了作用域:{标}",
                       "循环/迭代/并行的子图只能从容器节点进出 —— "
                       "**从外面直接连进子图,循环第几轮的那个节点是哪一个说不清**",
                       edge=标))
            continue
        后继[a].append(b)

    # ③ 每个作用域:可达性 + 环 + 支配关系 ──────────────────────────
    入口 = {None: (开始们[0] if 开始们 else None)}
    for 容器, ns in 按域.items():
        if 容器 is None:
            continue
        # 子图入口 = 容器节点经 循环体/支路 端口连到的那个
        子入口 = [e.get("target") for e in 边们
                 if e.get("source") == 容器
                 and e.get("port") in (DS.循环体, DS.支路)
                 and 属于.get(e.get("target")) == 容器]
        if not 子入口:
            出.append(问(阻断, "SCOPE_NO_ENTRY",
                       f"容器 {容器} 的子图没有入口",
                       "从容器节点的「循环体」端口连一条边到子图的第一个节点",
                       node_id=容器))
        入口[容器] = 子入口[0] if 子入口 else None

    # 容器节点必须真的有子图。⚠️ 这条是「集合相等」抓到的**漏报**:
    # 上面那个循环只遍历「有节点的作用域」,于是一个**空的**循环容器
    # 根本不在遍历里 —— 校验器一个字都不说,而那张图跑起来什么都不会做。
    for n in 节点们:
        i, t = n.get("id"), n.get("type")
        if t not in {x["名"] for x in DS.节点表}:
            continue
        if not DS.找节点(t)["可含子图"]:
            continue
        if not [x for x in 节点们 if x.get("container") == i]:
            出.append(问(阻断, "CONTAINER_EMPTY",
                       f"「{DS.找节点(t)['中文']}」{i} 里面是空的",
                       "把子图里的节点的 container 设成这个容器的 id —— "
                       "一个空的循环容器跑起来什么都不做,而画布上它是个正常的节点",
                       node_id=i))

    可达, dom = {}, {}
    for 容器, ns in 按域.items():
        e0 = 入口.get(容器)
        全 = {n["id"] for n in ns if n.get("id")}
        r = _可达(e0, 后继) & 全 if e0 else set()
        可达[容器] = r
        dom[容器] = 支配集(e0, 后继, r) if e0 else {}
        # 不可达
        for i in sorted(全 - r):
            级 = 阻断 if 按id[i].get("type") == "end" else 警告
            出.append(问(级, "NODE_UNREACHABLE",
                       f"节点 {i} 从入口走不到",
                       "补一条连线,或者删掉它 —— "
                       "**一个走不到的结束节点意味着这条流程没有出口**", node_id=i))
        # 环:顶层不许有(循环容器里的子图也不许有 —— 循环由容器表达,
        # 不由反向连线表达,否则「循环了几轮」和「图里有个环」混成一件事)
        环 = _找环(e0, 后继, r) if e0 else None
        if 环:
            出.append(问(阻断, "GRAPH_CYCLE",
                       f"{'顶层' if 容器 is None else '容器 ' + 容器 + ' 的子图'}里有环:"
                       f"{' → '.join(环)}",
                       "循环要用**有界循环**或**列表迭代**容器表达(它带次数上限),"
                       "**不能靠反向连线造环**(§5.2)—— 反向连线没有上限,也没有计数"))

    # ④ 条件分支必须有兜底 ─────────────────────────────────────────
    for n in 节点们:
        if n.get("type") != "condition":
            continue
        i = n.get("id")
        cfg = n.get("config") or {}
        分支键 = {b.get("key") for b in (cfg.get("branches") or [])
                 if isinstance(b, dict)}
        出边键 = {e.get("branch_key") for e in 边们 if e.get("source") == i}
        兜底 = ("else" in 出边键) or cfg.get("else_policy") in ("fail", "end")
        if not 兜底:
            出.append(问(阻断, "COND_NO_ELSE",
                       "条件分支没有兜底(既没有 ELSE 边,也没有显式终止策略)",
                       "连一条 branch_key=\"else\" 的边,或者把 else_policy 设成 "
                       "fail/end —— **没有兜底的条件在运行时是一条死路**,"
                       "而它在画布上看不出来(§6.1)", node_id=i,
                       field_path="config.else_policy"))
        # 声明了分支但没连线出去
        for k in sorted(分支键 - 出边键):
            出.append(问(阻断, "COND_BRANCH_NO_EDGE",
                       f"分支 {k!r} 没有连线出去",
                       f"给这个分支连一条边,或者从 branches 里删掉它",
                       node_id=i, field_path=f"config.branches[{k}]"))
        for k in sorted(出边键 - 分支键 - {"else", None}):
            出.append(问(阻断, "COND_EDGE_NO_BRANCH",
                       f"有一条 branch_key={k!r} 的连线,但 branches 里没有这个分支",
                       "在 branches 里加上这个分支条件,或者改这条边的 branch_key",
                       node_id=i))

    # ⑤ 变量可用性:**靠支配关系,不靠找名字** ───────────────────────
    跳过 = []
    for n in 节点们:
        i, t = n.get("id"), n.get("type")
        if i not in 按id or t not in {x["名"] for x in DS.节点表}:
            continue
        元 = DS.找节点(t)
        域 = 属于.get(i)
        可见域 = set(_祖先域(域, 属于))
        cfg = n.get("config") or {}
        绑定 = cfg.get("bindings") or {}
        if not isinstance(绑定, dict):
            出.append(问(阻断, "BIND_NOT_OBJECT", f"节点 {i} 的 bindings 不是对象",
                       "bindings 是 {字段名: 引用} 这种结构", node_id=i))
            continue
        for 字段, 引用 in 绑定.items():
            fp = f"config.bindings.{字段}"
            if not isinstance(引用, dict) or "source" not in 引用:
                出.append(问(阻断, "BIND_NOT_STRUCTURED",
                           f"{字段} 的绑定不是结构化引用",
                           "绑定要写成 {\"source\": ..., ...};"
                           "**文案里的 {{...}} 只是展示**,不是引用(§7.1)",
                           node_id=i, field_path=fp))
                continue
            src = 引用["source"]
            try:
                来源 = DS.找来源(src)
            except KeyError:
                出.append(问(阻断, "BIND_UNKNOWN_SOURCE",
                           f"{字段} 用了认不出的变量来源 {src!r}",
                           f"来源只能是 {[v['名'] for v in DS.变量来源表]}",
                           node_id=i, field_path=fp))
                continue
            # **密钥绝不进模型上下文**(§7.1)
            if not 来源["进模型上下文"] and t in ("llm", "agent"):
                出.append(问(阻断, "BIND_SECRET_INTO_MODEL",
                           f"{字段} 把「{来源['中文']}」绑进了会进模型上下文的节点",
                           "密钥只能在连接层用(secret_ref)。"
                           "**进过一次提示词,它就已经进过日志、Trace,可能进过导出**",
                           node_id=i, field_path=fp))
            if src != "node":
                continue
            m = 引用.get("node_id")
            if m not in 按id:
                出.append(问(阻断, "BIND_NODE_NOT_FOUND",
                           f"{字段} 引用了不存在的节点 {m!r}",
                           "选一个存在的上游节点 —— "
                           "复制节点之后忘记改引用是最常见的来源(§5.2)",
                           node_id=i, field_path=fp))
                continue
            # 跨作用域引用局部变量
            if 属于.get(m) not in 可见域:
                出.append(问(阻断, "BIND_CROSS_SCOPE",
                           f"{字段} 引用了另一个作用域里的节点 {m}",
                           "循环/迭代内部的节点输出是**局部**的 —— "
                           "出了那个作用域它就不存在了。要往外传就经容器的输出字段",
                           node_id=i, field_path=fp))
                continue
            # ⚠️ **这里是整个校验器的重点。**
            # 不问「m 这个节点在不在图里」(在,而且总是在),
            # 问「从入口到 i 的**每一条路径**是不是都必经 m」。
            d = dom.get(域, {})
            if i not in d:
                continue                      # i 自己不可达,上面已经报过
            if m == i:
                出.append(问(阻断, "BIND_SELF",
                           f"{字段} 引用了自己的输出", "改成引用上游节点",
                           node_id=i, field_path=fp))
            elif m not in d[i]:
                同域 = [x for x in 节点们 if 属于.get(x.get("id")) == 域]
                汇合们 = [x["id"] for x in 同域 if x.get("type") == "merge"]
                出.append(问(阻断, "BIND_MAYBE_MISSING",
                           f"{字段} 读的是节点 {m} 的输出,"
                           f"但**不是每条路径都会经过 {m}**",
                           "这通常是跨分支取值:某个分支不跑 " + m +
                           ",到这里那个字段就不存在。"
                           "加一个**分支汇合**节点把几路的值并成一个字段再读它"
                           + (f"(这个作用域里已有汇合节点:{汇合们})" if 汇合们 else "")
                           + " —— 规格 §7.2:『只在某一分支有值的变量,"
                             "不许被所有路径必填使用』",
                           node_id=i, field_path=fp))

    # ⑥ 依赖引用:存在、同项目、有权限 —— 由调用方提供查询能力 ────────
    引用字段 = {"connection_version_id": "连接版本", "prompt_version_id": "Prompt 版本",
              "tool_version_id": "工具版本", "agent_version_id": "Agent 版本",
              "knowledge_base_id": "知识库", "index_build_id": "索引构建",
              "retrieval_config_version_id": "检索配置版本",
              "workflow_version_id": "工作流版本"}
    if 依赖存在 is None:
        跳过.append("引用的依赖存不存在(调用方没给查询能力)—— "
                    "**这不算通过,是没查**")
    else:
        for n in 节点们:
            cfg = n.get("config") or {}
            for f, 中文 in 引用字段.items():
                v = cfg.get(f)
                if v and not 依赖存在(f, v):
                    出.append(问(阻断, "REF_NOT_FOUND",
                               f"{中文} {v} 不存在、无权访问或已撤回",
                               "换一个当前项目里有权访问的版本。"
                               "**外部导入的连接 ID 不能直接继承本地凭证**(§4.1)",
                               node_id=n.get("id"), field_path=f"config.{f}"))

    # ⑦ 子额度不许超过父额度(§13.2:嵌套不能重新拿一份完整预算)────────
    if 父额度:
        for n in 节点们:
            if n.get("type") not in ("agent", "subworkflow"):
                continue
            子 = (n.get("config") or {}).get("sub_limits") or {}
            超 = [k for k, v in 子.items()
                  if k in 父额度 and isinstance(v, (int, float))
                  and isinstance(父额度.get(k), (int, float)) and v > 父额度[k]]
            for k in 超:
                出.append(问(阻断, "SUB_LIMIT_EXCEEDS_PARENT",
                           f"子任务的 {k}({子[k]})超过了父流程的额度({父额度[k]})",
                           "子额度只能小于等于父额度 —— "
                           "**每嵌套一层重新拿一份完整预算,等于预算上限可以靠嵌套突破**",
                           node_id=n.get("id"), field_path=f"config.sub_limits.{k}"))

    # ⑧ 结束节点:必需输出字段要有合法来源 ─────────────────────────
    输出 = 定义.get("output_schema") or {}
    必需 = set(输出.get("required") or [])
    for i in 结束们:
        绑 = ((按id[i].get("config") or {}).get("bindings") or {})
        for f in sorted(必需 - set(绑)):
            出.append(问(阻断, "END_MISSING_OUTPUT",
                       f"输出 Schema 里 {f} 是必需的,但结束节点没有映射它",
                       f"在结束节点把 {f} 绑到一个上游输出 —— "
                       f"**「返回成功」和「任务达标」是两件事**(§6.1),"
                       f"而缺一个必需字段连前者都不成立", node_id=i,
                       field_path=f"config.bindings.{f}"))

    for s in 跳过:
        出.append(问(警告, "CHECK_SKIPPED", f"这一类没查:{s}",
                   "补上查询能力再跑一遍;**跳过的检查不能写成通过**(§C.4)"))
    return 出


def 有阻断(问题们):
    return any(p["级别"] == 阻断 for p in 问题们)


def 报告(问题们):
    """给接口返回用的结构(规格 §17.1:带 node_id / field_path / 阻断级别)。"""
    return dict(
        通过=not 有阻断(问题们),
        阻断数=sum(1 for p in 问题们 if p["级别"] == 阻断),
        警告数=sum(1 for p in 问题们 if p["级别"] == 警告),
        问题=问题们,
        说明="**客户端校验通过不代替服务端校验通过**(§5.3);"
             "而服务端校验通过也只说明**定义**合法 —— 不说明模型答得对、"
             "也不说明外部服务可用(附录 A-1 的局限)",
    )
