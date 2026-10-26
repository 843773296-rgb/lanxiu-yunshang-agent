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


# ── 报错写给谁看 ───────────────────────────────────────────────────
# 看这份报告的是配流程的业务人员,不是研发(用户 10-26 拍:「报错改人话」,方案文档 §6.1 那句样例
# 「还没有选择模型。请选择一个可用模型后测试。当前项目没有可用模型时,请联系平台管理员。」)。
# 所以 `消息` / `建议` 里:**不出现内部 id、英文字段名、规格章节号** —— 界面已经按 node_id 把步骤名标在前面,
# 按 field_path 把字段的中文名标在前面,消息只说「哪里不对 · 怎么改 · 改不了找谁」。
# 为什么这么判(支配关系、作用域那些)留在代码注释里,不塞给配置者。
# `code` 照旧是英文 —— 测试和前端按它分流,它不给人看。
def _称(n):
    """报错里怎么叫一个步骤:用人起的名字,没起名就用类型的中文名。"""
    if not isinstance(n, dict):
        return "「已删除的步骤」"
    名 = (n.get("name") or "").strip()
    if not 名:
        try:
            名 = DS.找节点(n.get("type"))["中文"]
        except KeyError:
            名 = "未知步骤"
    return f"「{名}」"


# 必填项没填时说什么。(什么没填, 去哪填)—— 位置对着编辑页右侧面板的四段:基本 / 用到的数据 / 结果 / 高级
_缺项说法 = {
    "input_schema": ("还没写使用者要提供什么", "在右侧「基本」里加上使用者要填的内容,比如录音、客户编号"),
    "connection_version_id": ("还没有选择模型",
                              "在右侧「基本」里选一个可用模型。下拉里一个都没有时,请联系平台管理员接入模型"),
    "prompt_version_id": ("还没有选这一步要完成什么(处理要求)",
                          "在右侧「基本」里选一份处理要求。还没有的话,先去「Prompt 管理」写一份并保存版本"),
    "output_schema": ("还没写这一步的结果包含哪些内容", "在右侧「结果」里至少加一项结果"),
    "tool_version_id": ("还没有选执行哪个业务动作",
                        "在右侧「基本」里选一个业务动作。下拉里没有你要的,请联系平台管理员登记"),
    "branches": ("还没有设置分支条件", "在右侧「基本」里点「加一路」,写上满足什么条件走这一路"),
    "else_policy": ("还没选都不满足时怎么办", "在右侧「基本」里选「记成没完成」或「正常结束」"),
    "operations": ("还没写怎么整理数据", "在右侧面板里至少加一条整理规则"),
    "candidates": ("还没选要汇合哪几路", "在右侧「用到的数据」里点「加一路」,选每一路的结果"),
    "output_field": ("还没给汇合后的结果起名", "在右侧「用到的数据」里填一个名字"),
    "request_kind": ("还没选核对类型", "在右侧「基本」里选一个核对类型"),
    "candidate_roles": ("还没选谁来处理", "在右侧「基本」里至少勾一个角色"),
    "expires_at_policy": ("还没设多久没处理就结束", "在右侧「基本」里填一个小时数,比如 48"),
    "knowledge_base_id": ("还没选查哪个资料库", "在右侧面板里选一个资料库。没有的话,先去「知识库」建一个"),
    "retrieval_config_version_id": ("还没选怎么查资料", "在右侧面板里选一套检索设置"),
    "agent_version_id": ("还没选用哪个 Agent", "在右侧面板里选一个已生成版本的 Agent"),
    "task_binding": ("还没写交给 Agent 的任务", "在右侧「用到的数据」里选任务内容从哪来"),
    "sub_limits": ("还没设这一步的上限", "在右侧「高级」里填最多跑几轮、最多花多少"),
}

# 引用的资源找不到时怎么叫它
_资源称呼 = {"connection_version_id": "选的模型", "prompt_version_id": "选的处理要求",
            "tool_version_id": "选的业务动作", "agent_version_id": "选的 Agent",
            "knowledge_base_id": "选的资料库", "index_build_id": "选的资料库索引",
            "retrieval_config_version_id": "选的检索设置",
            "workflow_version_id": "选的子流程"}


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
    # ①里这几条(定义形状不对、缺 id、重复 id、没登记的字段)从编辑页里点不出来,
    # 只会来自导入的文件或直接调接口 —— 所以建议是「撤回 / 找技术管理员」,不是「去面板里改」。
    坏图建议 = "撤销到上一次保存的版本,或重新导入。还不行请联系技术管理员"
    if not isinstance(定义, dict):
        return [问(阻断, "DEF_NOT_OBJECT", "这条流程的数据格式损坏了,读不出来", 坏图建议)]
    节点们 = 定义.get("nodes")
    边们 = 定义.get("edges")
    if not isinstance(节点们, list) or not 节点们:
        出.append(问(阻断, "DEF_NO_NODES", "流程里一个步骤都没有",
                   "至少加一个「开始」和一个「结束」,中间放要做的步骤"))
        return 出
    if not isinstance(边们, list):
        # 缺这个键和「一条边都没有」不是一回事:前者是数据坏了
        边们 = []
        出.append(问(阻断, "DEF_NO_EDGES", "流程的连线数据丢了", 坏图建议))

    # 重复 ID:**先查这条**。后面所有按 id 查节点的逻辑都建立在 id 唯一上,
    # 重复的话「按 id 找到的那个」是哪一个取决于遍历顺序 —— 而那不是确定语义。
    见过, 重复 = set(), []
    for n in 节点们:
        i = n.get("id")
        if not i:
            # 稳定 id 不随名称改变(规格 §5.2)—— 没有它,别的步骤没法引用这一步
            出.append(问(阻断, "NODE_NO_ID", f"{_称(n)}缺少内部编号,别的步骤没法引用它", 坏图建议))
            continue
        if i in 见过:
            重复.append(i)
        见过.add(i)
    for i in sorted(set(重复)):
        # 复制节点没生成新 id 是最常见的来源(§5.2)
        出.append(问(阻断, "NODE_DUP_ID", "有两个步骤用了同一个内部编号,系统分不清引用的是哪一个",
                   "删掉其中一个再重新添加。重新添加后,检查后面步骤「用到的数据」是不是还指着它",
                   node_id=i))
    按id = {n.get("id"): n for n in 节点们 if n.get("id")}

    # 未知节点类型 / 未实现的节点
    for n in 节点们:
        t, i = n.get("type"), n.get("id")
        try:
            元 = DS.找节点(t)
        except KeyError:
            出.append(问(阻断, "NODE_UNKNOWN_TYPE", "这个步骤的类型系统不认识,可能来自别的系统或旧版本",
                       "删掉它,从「＋ 添加步骤」里重新选一个",
                       node_id=i))
            continue
        if 元["实现"] == DS.未实现:
            # **不摆空按钮冒充可用**(§6.1)。这条是阻断:一张用了未实现节点的图
            # 能冻结、能发布,然后在运行时才发现跑不了 —— 那比现在拦住贵得多。
            出.append(问(阻断, "NODE_NOT_IMPLEMENTED",
                       f"「{元['中文']}」这类步骤还不能运行",
                       f"换成能用的步骤搭出同样的流程:{'、'.join(x['中文'] for x in DS.可用节点())}",
                       node_id=i))
        # 必填配置
        cfg = n.get("config") or {}
        for f in 元["必填"]:
            if f not in cfg or cfg[f] in (None, "", [], {}):
                什么, 去哪 = _缺项说法.get(f, ("有一项必填的还没填", "在右侧面板里把标了必填的填上"))
                出.append(问(阻断, "NODE_MISSING_CONFIG", 什么, 去哪,
                           node_id=i, field_path=f"config.{f}"))
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
        # 没登记的字段不会有任何地方读它,填了不算 —— 这只会来自导入或直接调接口
        for k in 野:
            出.append(问(阻断, "NODE_UNKNOWN_CONFIG",
                       "这一步带着一项系统不认识的设置,填了也不会生效", 坏图建议,
                       node_id=i, field_path=f"config.{k}"))
        # 通用字段里标了「不适用」的,不许出现在配置里(§6:不许有拧了不算数的设置)
        for k in 元["不适用"]:
            if k in cfg:
                出.append(问(阻断, "NODE_INAPPLICABLE_FIELD",
                           f"「{元['中文']}」这类步骤用不上这项设置,填了也不会生效",
                           f"在右侧「高级」里把它清空"
                           + ("(这一步不调用外部服务,不存在超时和重试)"
                              if k in ('timeout_seconds', 'retryable_errors', 'max_retries') else ""),
                           node_id=i, field_path=f"config.{k}"))

    # 开始 / 结束
    开始们 = [n["id"] for n in 节点们 if n.get("type") == "start" and n.get("id")]
    结束们 = [n["id"] for n in 节点们 if n.get("type") == "end" and n.get("id")]
    if not 开始们:
        出.append(问(阻断, "GRAPH_NO_START", "流程没有「开始」",
                   "加一个「开始」,在它的「基本」里写使用者要提供什么"))
    if len(开始们) > 1:
        # 每个顶层 Workflow 只能有一个开始(§6.1),否则「从哪儿开始执行」不确定
        出.append(问(阻断, "GRAPH_MULTI_START",
                   f"流程有 {len(开始们)} 个「开始」,系统不知道从哪个开始跑",
                   "只留一个「开始」,把其余的删掉"))
    if not 结束们:
        出.append(问(阻断, "GRAPH_NO_END", "流程没有「结束」",
                   "加一个「结束」,在它的「结果」里写最后要返回哪些内容"))

    # ② 连线 ────────────────────────────────────────────────────────
    按域, 属于 = _作用域(节点们)
    后继 = {i: [] for i in 按id}
    for e in 边们:
        a, b, p = e.get("source"), e.get("target"), e.get("port")
        标 = f"{a} --{p}--> {b}"
        if a not in 按id or b not in 按id:
            出.append(问(阻断, "EDGE_DANGLING",
                       "从这一步出发的一条连线,终点的步骤已经不在了" if a in 按id
                       else "有一条连线的起点步骤已经不在了",
                       "删掉这条连线,重新连到要去的步骤",
                       node_id=a if a in 按id else None, edge=标))
            continue
        元a = DS.找节点(按id[a]["type"]) if 按id[a].get("type") in \
            {x["名"] for x in DS.节点表} else None
        if 元a and p not in 元a["端口"]:
            出.append(问(阻断, "EDGE_UNKNOWN_PORT",
                       f"从这一步连到{_称(按id[b])}的线,接在了一个不存在的出口上",
                       "删掉这条连线,从这一步的出口重新拖一条", node_id=a, edge=标))
            continue
        # 跨作用域连线:只允许容器 → 它自己的子图(循环体),或同一作用域内。
        # 从外面直接连进子图,「循环第几轮的那个节点」是哪一个说不清
        域a, 域b = 属于.get(a), 属于.get(b)
        if 域a != 域b and not (域b == a) and not (域a == b):
            出.append(问(阻断, "EDGE_CROSS_SCOPE",
                       f"这条线从循环外面直接连进了循环里面({_称(按id[a])} → {_称(按id[b])})",
                       "循环里面的步骤只能从循环本身进出。删掉这条线,改连到循环步骤上",
                       node_id=a, edge=标))
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
                       "循环里面的步骤没有连上,跑到这里不知道先做哪一步",
                       "从这一步连一条线到循环里的第一步",
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
                       f"这个「{DS.找节点(t)['中文']}」里面没有步骤,跑起来什么都不会做",
                       "往里面放至少一个步骤,或者删掉它",
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
            # 走不到的「结束」= 这条流程没有出口,所以它是阻断;别的步骤走不到只是白放着
            是结束 = 按id[i].get("type") == "end"
            出.append(问(阻断 if 是结束 else 警告, "NODE_UNREACHABLE",
                       "从「开始」走不到这一步" + (",流程没有出口" if 是结束 else ",它永远不会被执行"),
                       "从前面某一步连一条线到它" + ("" if 是结束 else ";用不上就删掉"),
                       node_id=i))
        # 环:顶层不许有(循环容器里的子图也不许有 —— 循环由容器表达,
        # 不由反向连线表达,否则「循环了几轮」和「图里有个环」混成一件事;反向连线没有次数上限 §5.2)
        环 = _找环(e0, 后继, r) if e0 else None
        if 环:
            出.append(问(阻断, "GRAPH_CYCLE",
                       f"有连线往回连,流程会绕圈停不下来:{' → '.join(_称(按id.get(x)) for x in 环)}",
                       "删掉往回连的那条线。确实要重复做的,用「有界循环」或「列表迭代」步骤,它们带次数上限",
                       node_id=环[-2] if len(环) > 1 else None))

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
        # else_policy 整个没填时,上面「必填」那条已经报了同一个字段 —— 不再报第二条
        # (同一处两条不同说法,人会以为是两个问题;10-26 改人话时看出来的多报)
        if not 兜底 and cfg.get("else_policy") not in (None, "", [], {}):
            # 没有兜底的条件在运行时是一条死路,而它在画布上看不出来(§6.1)
            出.append(问(阻断, "COND_NO_ELSE",
                       "所有条件都不满足时,流程不知道往哪走",
                       "在右侧「基本」的「都不满足时怎么办」里选一项,或者从「都不满足」出口连一条线",
                       node_id=i, field_path="config.else_policy"))
        # 声明了分支但没连线出去(分支名是配置者自己起的,原样用)
        for k in sorted(分支键 - 出边键):
            出.append(问(阻断, "COND_BRANCH_NO_EDGE",
                       f"「{k}」这一路没有连到下一步",
                       "从这一路的出口连一条线到下一步;用不上就在「基本」里删掉这一路",
                       node_id=i, field_path=f"config.branches[{k}]"))
        for k in sorted(出边键 - 分支键 - {"else", None}):
            出.append(问(阻断, "COND_EDGE_NO_BRANCH",
                       f"有一条连线挂在「{k}」这一路上,但条件里已经没有这一路了",
                       "删掉这条线;还要这一路的话,先在「基本」里把它加回来再连",
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
            出.append(问(阻断, "BIND_NOT_OBJECT", "这一步「用到的数据」的设置损坏了,读不出来",
                       "在右侧「用到的数据」里把每一项重新选一遍。还不行请联系技术管理员", node_id=i))
            continue
        for 字段, 引用 in 绑定.items():
            fp = f"config.bindings.{字段}"
            if not isinstance(引用, dict) or "source" not in 引用:
                # 文案里的 {{...}} 只是展示,不是引用(§7.1)—— 手写的占位符不会被替换成真数据
                出.append(问(阻断, "BIND_NOT_STRUCTURED",
                           f"「{字段}」是手写的,系统不知道它的数据从哪来",
                           f"在右侧「用到的数据」里给「{字段}」从下拉里重新选来源",
                           node_id=i, field_path=fp))
                continue
            src = 引用["source"]
            try:
                来源 = DS.找来源(src)
            except KeyError:
                出.append(问(阻断, "BIND_UNKNOWN_SOURCE",
                           f"「{字段}」的数据来源系统不认识",
                           f"在右侧「用到的数据」里给「{字段}」重新选来源"
                           f"(可选:{'、'.join(v['中文'] for v in DS.变量来源表 if v['名'] != 'secret')})",
                           node_id=i, field_path=fp))
                continue
            # **密钥绝不进模型上下文**(§7.1):进过一次提示词,它就已经进过日志、Trace,可能进过导出
            if not 来源["进模型上下文"] and t in ("llm", "agent"):
                出.append(问(阻断, "BIND_SECRET_INTO_MODEL",
                           f"「{字段}」用的是密钥,而这一步会把内容交给模型,密钥会被记进日志",
                           f"在右侧「用到的数据」里给「{字段}」换一个来源。"
                           "接外部服务要用的密钥,请平台管理员配在「模型与连接」里",
                           node_id=i, field_path=fp))
            if src != "node":
                continue
            m = 引用.get("node_id")
            if m not in 按id:
                # 复制节点之后忘记改引用是最常见的来源(§5.2)
                出.append(问(阻断, "BIND_NODE_NOT_FOUND",
                           f"「{字段}」取数的那一步已经被删掉了",
                           f"在右侧「用到的数据」里给「{字段}」重新选一个前面步骤的结果",
                           node_id=i, field_path=fp))
                continue
            # 跨作用域引用局部变量:循环内部的输出出了那个作用域就不存在了
            if 属于.get(m) not in 可见域:
                出.append(问(阻断, "BIND_CROSS_SCOPE",
                           f"「{字段}」取的是循环里面{_称(按id[m])}的结果,出了循环就拿不到",
                           "改成取循环这一步自己的结果",
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
                           f"「{字段}」取的是这一步自己的结果,可这一步还没跑完",
                           f"在右侧「用到的数据」里给「{字段}」改选前面某一步的结果",
                           node_id=i, field_path=fp))
            elif m not in d[i]:
                # 规格 §7.2:「只在某一分支有值的变量,不许被所有路径必填使用」—— 判据是支配关系,见文件头
                同域 = [x for x in 节点们 if 属于.get(x.get("id")) == 域]
                汇合们 = [x for x in 同域 if x.get("type") == "merge"]
                出.append(问(阻断, "BIND_MAYBE_MISSING",
                           f"「{字段}」取的是{_称(按id[m])}的结果,但走另一条分支时{_称(按id[m])}不会执行,"
                           f"到这里就取不到值",
                           "在分支之后加一个「分支汇合」,把几条分支的结果并成一项,再从汇合那一步取"
                           + (f"(流程里已经有:{'、'.join(_称(x) for x in 汇合们)})" if 汇合们 else ""),
                           node_id=i, field_path=fp))

    # ⑥ 依赖引用:存在、同项目、有权限 —— 由调用方提供查询能力 ────────
    引用字段 = {"connection_version_id": "连接版本", "prompt_version_id": "Prompt 版本",
              "tool_version_id": "工具版本", "agent_version_id": "Agent 版本",
              "knowledge_base_id": "知识库", "index_build_id": "索引构建",
              "retrieval_config_version_id": "检索配置版本",
              "workflow_version_id": "工作流版本"}
    if 依赖存在 is None:
        跳过.append("选的模型、处理要求、业务动作这些还在不在(这次没给查询能力)—— 这不算通过,是没查")
    else:
        for n in 节点们:
            cfg = n.get("config") or {}
            for f, 中文 in 引用字段.items():
                v = cfg.get(f)
                if v and not 依赖存在(f, v):
                    # 外部导入的连接 ID 不能直接继承本地凭证(§4.1)—— 所以导入的图常在这里红
                    出.append(问(阻断, "REF_NOT_FOUND",
                               f"{_资源称呼.get(f, 中文)}已经用不了:被删了、撤回了,或者你没有权限用它",
                               "在右侧「基本」里重新选一个。导入的流程常见这种情况,要在本项目里重新选一遍。"
                               "下拉里没有能用的,请联系平台管理员",
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
            # 每嵌套一层重新拿一份完整预算,等于预算上限可以靠嵌套突破
            for k in 超:
                出.append(问(阻断, "SUB_LIMIT_EXCEEDS_PARENT",
                           f"这一步的上限({子[k]})比整条流程的上限({父额度[k]})还高",
                           f"在右侧「高级」里把它改到 {父额度[k]} 或更低",
                           node_id=n.get("id"), field_path=f"config.sub_limits.{k}"))

    # ⑧ 结束节点:必需输出字段要有合法来源 ─────────────────────────
    输出 = 定义.get("output_schema") or {}
    必需 = set(输出.get("required") or [])
    for i in 结束们:
        绑 = ((按id[i].get("config") or {}).get("bindings") or {})
        # 「返回成功」和「任务达标」是两件事(§6.1),而缺一个必需字段连前者都不成立
        for f in sorted(必需 - set(绑)):
            出.append(问(阻断, "END_MISSING_OUTPUT",
                       f"最后要返回「{f}」,但还没选它从哪来",
                       f"在右侧「用到的数据」里给「{f}」选一个前面步骤的结果", node_id=i,
                       field_path=f"config.bindings.{f}"))

    # 跳过的检查不能写成通过(§C.4)
    for s in 跳过:
        出.append(问(警告, "CHECK_SKIPPED", f"有一类没检查:{s}",
                   "这次结论不完整。请重新点一次「检查配置」;一直这样请联系技术管理员"))
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


# ══════════════════════════════════════════════════════════════════
# Agent 配置校验(规格 §9.3、§9.4、§9.5、§9.6、附录 D.2)
# ══════════════════════════════════════════════════════════════════
#
# ## 和图校验不同的地方:这里大半的判据是「**这个声明有没有落点**」
#
# 一张图配错了,跑一次就看得出来(节点没激活、变量取不到值)。
# 一个 Agent 配错了**跑一次看不出来** —— 它会输出一段看起来挺像的文字。
# 所以这里的判据集中在「声明和现实对不对得上」:
#
#   · 「必要证据」里点名的字段,在 output_schema 里**存在吗**?
#     不存在的话,那条判据永远查不到东西,而它在界面上是填好的。
#   · 选的模型连接**声明了支持原生工具调用吗**?
#     §9.3 要「原生工具调用能力检查」,附录 D.2 补了一句
#     「**不按模型家族名字推断兼容**」—— 能不能按契约调工具是按型号来的,
#     而「它是个大模型所以应该行」是这一块最贵的假设。
#   · 给了会做不可逆写入的工具,配了确认策略吗?
#
# > **一个永远查不到东西的判据,和没有这条判据,在界面上长得一模一样。**
def 校验Agent(配置, *, 依赖存在=None, 连接能力=None, 工具目录=None, 项目上限=None):
    """返回问题清单。`连接能力(connection_version_id) -> dict` 由调用方给。"""
    出 = []
    if not isinstance(配置, dict):
        return [问(阻断, "AGENT_NOT_OBJECT", "Agent 配置不是一个对象",
                  "检查提交的 JSON 顶层形状")]
    跳过 = []

    # ① 必填
    for f, 中文 in (("connection_version_id", "模型连接版本"),
                   ("prompt_version_id", "指令 Prompt 版本"),
                   ("task_template", "目标模板"),
                   ("output_schema", "输出契约"),
                   ("limits", "运行限制")):
        v = 配置.get(f)
        if not v:
            出.append(问(阻断, "AGENT_MISSING", f"缺 {中文}",
                       f"在「行为配置」里把 {中文} 填上", field_path=f))

    # ② 引用存在(按项目范围查,由调用方提供)
    if 依赖存在 is None:
        跳过.append("引用的依赖存不存在(调用方没给查询能力)")
    else:
        for f in ("connection_version_id", "prompt_version_id"):
            v = 配置.get(f)
            if v and not 依赖存在(f, v):
                出.append(问(阻断, "REF_NOT_FOUND",
                           f"{f} = {v} 不存在、无权访问或已撤回",
                           "换一个当前项目里有权访问的版本", field_path=f))
        for i, t in enumerate(配置.get("tools") or []):
            tv = t.get("tool_version_id") if isinstance(t, dict) else t
            if tv and not 依赖存在("tool_version_id", tv):
                出.append(问(阻断, "REF_NOT_FOUND",
                           f"工具版本 {tv} 不存在或无权使用",
                           "在「工具与知识」里重新选一个已注册的工具版本",
                           field_path=f"tools[{i}]"))

    # ③ **原生工具调用能力检查**(§9.3 + 附录 D.2)
    cv = 配置.get("connection_version_id")
    if 连接能力 is None:
        跳过.append("模型连接的能力(调用方没给探测结果)—— "
                    "**这一条不查等于按名字推断兼容**")
    elif cv:
        能力 = 连接能力(cv) or {}
        要工具 = bool(配置.get("tools"))
        if 要工具 and not 能力.get("原生工具调用"):
            出.append(问(阻断, "MODEL_NO_TOOL_CALLING",
                       f"这个模型连接**没有声明支持原生工具调用**,"
                       f"而这个 Agent 给了 {len(配置.get('tools') or [])} 个工具",
                       "换一个声明了支持的连接,或者把工具全去掉做一个纯生成 Agent。"
                       "**不按模型家族名字推断兼容**(附录 D.2)—— "
                       "能不能按契约调工具是按型号来的;"
                       "连接的 capabilities 要靠**探测**填,不是靠猜",
                       field_path="connection_version_id"))
        if 能力.get("execution_mode") == "mock" and not 能力.get("原生工具调用"):
            出.append(问(警告, "MOCK_CONNECTION",
                       "这是一条 mock 连接 —— 跑出来的结果不代表真实智能能力",
                       "生产发布会拒绝 mock 产物和 mock 验收报告(§19.4)"))

    # ④ 工具:不可逆写入必须有确认策略
    for i, t in enumerate(配置.get("tools") or []):
        tv = t.get("tool_version_id") if isinstance(t, dict) else t
        契 = (工具目录 or {}).get(tv) or {}
        if 契.get("side_effect_type") == DS.不可逆 and not 契.get("confirmation_policy"):
            出.append(问(阻断, "TOOL_NO_CONFIRMATION",
                       f"工具 {tv} 会做**不可逆写入**,但没有确认策略",
                       "在工具版本上配 confirmation_policy —— "
                       "**不可逆写入必须有绑定了参数摘要的人工确认**(§12.2),"
                       "而且**模型不能批准自己**(§9.6)",
                       field_path=f"tools[{i}]"))

    # ⑤ 运行限制:必须有,而且必须是正数
    限 = 配置.get("limits") or {}
    for k, 中文 in (("max_model_turns", "最大模型回合数"),
                   ("max_tool_attempts", "最大工具调用数"),
                   ("deadline_seconds", "总执行期限")):
        v = 限.get(k)
        if v is None:
            出.append(问(阻断, "LIMIT_MISSING", f"没配 {中文}",
                       f"在「权限与限制」里填 {中文} —— "
                       f"**没有上限的自主循环没有已知的最坏情况**",
                       field_path=f"limits.{k}"))
        elif not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            出.append(问(阻断, "LIMIT_INVALID", f"{中文} 要是正整数,现在是 {v!r}",
                       "填一个正整数", field_path=f"limits.{k}"))
    if 项目上限:
        超 = [k for k, v in 限.items()
              if k in 项目上限 and isinstance(v, (int, float))
              and isinstance(项目上限.get(k), (int, float)) and v > 项目上限[k]]
        for k in 超:
            出.append(问(阻断, "LIMIT_EXCEEDS_PROJECT",
                       f"{k}({限[k]})超过了项目策略上限({项目上限[k]})",
                       "**运行预算和授权不由配置里的用户字段任意提升**(§16.5)",
                       field_path=f"limits.{k}"))

    # ⑥ 输出契约:必需字段不能空 —— 否则「完成」没有判据
    osc = 配置.get("output_schema") or {}
    必需 = osc.get("required") or []
    props = osc.get("properties") or {}
    if osc and not 必需:
        出.append(问(阻断, "OUTPUT_NO_REQUIRED",
                   "输出契约里一个必需字段都没有",
                   "至少声明一个必需字段 —— **一个什么都不要求的输出契约,"
                   "让「模型说完成了」直接变成「完成了」**(§10.2)",
                   field_path="output_schema.required"))

    # ⑦ **完成判据点名的字段必须真的存在**
    # 这一条是这整段里最容易被漏掉、也最像「已经在查了」的那种:
    # 一条点名了不存在字段的判据**永远查不到东西**,而它在界面上是填好的。
    判 = 配置.get("completion_criteria") or {}
    for 键 in 判.get("必要证据") or []:
        if 键 not in props:
            出.append(问(阻断, "CRITERION_FIELD_MISSING",
                       f"完成判据要求 {键!r} 非空,但输出契约里没有这个字段",
                       f"要么在 output_schema.properties 里加上 {键},"
                       f"要么把它从必要证据里去掉 —— "
                       f"**一条永远查不到东西的判据,和没有这条判据长得一模一样**",
                       field_path="completion_criteria.必要证据"))
    for 动作 in 判.get("必须做的动作") or []:
        名们 = [(t.get("tool_version_id") if isinstance(t, dict) else t)
               for t in (配置.get("tools") or [])]
        名们 += [((工具目录 or {}).get(x) or {}).get("name") for x in 名们]
        if 动作 not in [x for x in 名们 if x]:
            出.append(问(阻断, "CRITERION_TOOL_MISSING",
                       f"完成判据要求必须执行 {动作!r},但这个 Agent 没有这个工具",
                       "把那个工具授权给它,或者改判据 —— "
                       "**要求一个它做不到的动作,等于这个 Agent 永远不可能达标**",
                       field_path="completion_criteria.必须做的动作"))

    # ⑧ 长期记忆首版必须关闭(§9.5)
    ctx = 配置.get("context_policy") or {}
    if ctx.get("long_term_memory") not in (None, "disabled"):
        出.append(问(阻断, "LTM_NOT_SUPPORTED",
                   "长期记忆首版不支持",
                   "把 context_policy.long_term_memory 设成 disabled —— "
                   "**未经审核就持久化的错误事实会跨任务传染**,"
                   "而作用域、保留期限、撤回都还没实现(§9.5)",
                   field_path="context_policy.long_term_memory"))

    for s in 跳过:
        出.append(问(警告, "CHECK_SKIPPED", f"这一类没查:{s}",
                   "补上查询能力再跑一遍;**跳过的检查不能写成通过**(§C.4)"))
    return 出
