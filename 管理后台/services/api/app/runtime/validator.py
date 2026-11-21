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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 列表操作 as LO  # noqa: E402
import 文档提取 as DE  # noqa: E402
import 列表迭代 as FE  # noqa: E402
import 定时 as SCH  # noqa: E402
import 并行 as PL  # noqa: E402
import 子工作流 as SW  # noqa: E402

# 定时开头的流程,「开始」交给下一步的只有这两项(定时自己填)—— 别处也用这个名单(workflows_api 的 _定时统计字段 同一对)
定时自填 = ("统计起", "统计止")

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
    "code": ("还没写代码", "在右侧「代码」框里写一个 main(**inputs) 函数,返回一个字典"),
    "connection_id": ("还没有选用哪条工具连接去请求",
                      "在右侧「基本」里选一条已登记的工具连接 —— 地址白名单和凭据都挂在连接上;没有的话先到「工具连接」里登记"),
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
    "condition": ("还没写循环什么时候继续", "在右侧「基本」里写「满足什么条件就再跑一轮」,比如「还要重写 等于 是」"),
    "max_iterations": ("还没填最多跑几轮", "在右侧「基本」里填一个 1 到 10 的数;经营报告是 4(第一稿 + 最多重写 3 次)"),
    "assignments": ("还没写要改哪一项、怎么改", "在右侧「基本」里点「加一条」,选循环状态里的一项和改法"),
    "parameters": ("还没写要提取哪几项", "在右侧「基本」里至少加一项,写上名字、类型和说明"),
    "classes": ("还没写要分成哪几类", "在右侧「基本」里至少写两个类别,比如「有意向」「没意向」「说不清」"),
    "template": ("还没写要回复什么", "在右侧「基本」里写回复内容;要带上前面的结果,写 {{名字}} 并在「用到的数据」里给它选来源"),
    # 同一个字段在不同步骤里缺的是不同的东西(11-12):按 (步骤类型, 字段) 先找,找不到再按字段
    ("list_operator", "bindings"): ("还没选要处理哪个列表", "在右侧「用到的数据」里给「列表」选一个前面步骤给的列表"),
    ("doc_extractor", "bindings"): ("还没选从哪个文件取文字", "在右侧「用到的数据」里给「文件」选上传文件的那一项(比如开始节点里让使用者给的文件编号)"),
    ("foreach", "bindings"): ("还没选要逐项处理哪个列表", "在右侧「用到的数据」里给「列表」选一个前面步骤给的列表"),
    "item_output": ("还没选每一项做完交出什么", "在右侧「基本」里从下拉选迭代里面那一步的一项结果(比如 AI 处理 → text)"),
    "item_failure_policy": ("还没选某一项失败时怎么办", "在右侧「基本」里选:整步失败,或者留空位接着做下一项"),
    "max_items": ("还没填最多做几项", f"在右侧「基本」里填 1 到 {FE.技术上限} 的整数 —— 按这条流程一次该处理多少条来填,"
                  f"{FE.技术上限} 只是技术上限"),
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


# 结果字段固定的几类步骤,各字段的类型(11-12 列表迭代要判「选的是不是列表」)。认不出就是 None = 不知道,不猜
_固定结果类型 = {"list_operator": {"结果": "array", "个数": "integer"},
               "foreach": {"结果": "array", "个数": "integer", "失败项": "array"},
               "parallel": {"结果": "object", "状态": "object", "失败支路": "array"},
               "template": {"文本": "string"}, "answer": {"回复": "string"},
               "classifier": {"类别": "string", "理由": "string"}}


def _声明类型(引用, 按id):
    """一个引用指向的那一项**声明了**什么类型(只看定义,不看数据)。只认一层的 pointer;说不清就返回 None。"""
    if not isinstance(引用, dict):
        return None
    p = str(引用.get("pointer") or "").lstrip("/")
    if not p or "/" in p:
        return None
    if 引用.get("source") == "input":
        起 = next((n for n in 按id.values() if n.get("type") == "start"), None)
        props = (((起 or {}).get("config") or {}).get("input_schema") or {}).get("properties") or {}
        t = (props.get(p) or {}).get("type") if isinstance(props.get(p), dict) else None
        return t if isinstance(t, str) else None
    if 引用.get("source") == "node":
        m = 按id.get(引用.get("node_id"))
        if not m:
            return None
        if m.get("type") in _固定结果类型:
            return _固定结果类型[m["type"]].get(p)
        props = (((m.get("config") or {}).get("output_schema") or {}).get("properties") or {})
        t = (props.get(p) or {}).get("type") if isinstance(props.get(p), dict) else None
        return t if isinstance(t, str) else None
    return None


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
                什么, 去哪 = _缺项说法.get((t, f)) or _缺项说法.get(f, ("有一项必填的还没填", "在右侧面板里把标了必填的填上"))
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

    # 开始方式(11-16,台账第六十九条,照 Dify):「用户输入」或「定时」,**二选一** ——
    # 定时开头的流程没人在场填东西,「使用者要提供什么」里除了定时自己填的统计起 / 止,不许再有别的
    for n in 节点们:
        if n.get("type") != "start" or not n.get("id"):
            continue
        c = n.get("config") or {}
        方式 = c.get("start_mode") or "用户输入"
        if 方式 not in ("用户输入", "定时", "Webhook"):
            出.append(问(阻断, "START_MODE_UNKNOWN", f"「开始」的开始方式「{方式}」认不出",
                       "在「开始」的「基本」里选「用户输入」「定时触发器」或「Webhook」", node_id=n["id"], field_path="config.start_mode"))
            continue
        # Webhook 的三张参数表 + 返回内容(11-20 二期 2-2 尾巴,照 Dify 的 Query / Header / 响应配置):
        # 三张表的参数名不能撞(撞了运行时不知道取哪个);请求头只能是文字;返回状态码只许 200 / 202(契约里成功码);
        # 返回体模板里 {{名}} 只许引用登记过的参数或 运行编号 / 状态 / 跑的版本 / 查结果 —— 引用不存在的名字,对方收到的永远是空
        三表 = (("input_schema", "请求体参数"), ("webhook_query_schema", "网址参数"), ("webhook_header_schema", "请求头参数"))
        if 方式 == "Webhook":
            import re as _re
            名们 = {}
            for 键, 叫 in 三表:
                for 名, 定 in ((c.get(键) or {}).get("properties") or {}).items():
                    t = (定 or {}).get("type") or "string"
                    if 键 == "webhook_header_schema" and t != "string":
                        出.append(问(阻断, "WEBHOOK_HEADER_TYPE", f"请求头参数「{名}」登记成了{t},请求头只能是文字",
                                   "把它的类型改成「文本」;要数字就放到网址参数或请求体里", node_id=n["id"], field_path=f"config.webhook_header_schema.properties.{名}"))
                    if 名 in 名们:
                        出.append(问(阻断, "WEBHOOK_PARAM_DUP", f"「{名}」在{名们[名]}和{叫}里都登记了 —— 运行时不知道取哪个",
                                   "三张表里的参数名不能重复,给其中一个换个名字", node_id=n["id"], field_path=f"config.{键}.properties.{名}"))
                    else:
                        名们[名] = 叫
            回 = c.get("webhook_response")
            if 回 not in (None, {}):
                if not isinstance(回, dict) or ("body" in 回 and 回.get("body") is not None and not isinstance(回.get("body"), str)):
                    出.append(问(阻断, "WEBHOOK_RESPONSE_BAD", "「返回给对方什么」的形状不对", "状态码选 200 或 202,返回体是一段文字(可以写 {{参数名}} / {{运行编号}})",
                               node_id=n["id"], field_path="config.webhook_response"))
                else:
                    if 回.get("status_code", 202) not in (200, 202):
                        出.append(问(阻断, "WEBHOOK_RESPONSE_STATUS", f"返回状态码 {回.get('status_code')} 不在允许的范围(200 / 202)",
                                   "受理成功只能回 200 或 202;参数错、密钥错这些由系统按契约回 4xx,不在这里配", node_id=n["id"], field_path="config.webhook_response.status_code"))
                    for 名 in sorted(set(_re.findall(r"\{\{\s*([^{}\s]+)\s*\}\}", 回.get("body") or ""))):
                        if 名 not in 名们 and 名 not in ("运行编号", "状态", "跑的版本", "查结果"):
                            出.append(问(阻断, "WEBHOOK_RESPONSE_REF", f"返回体里引用了「{名}」,它不在三张参数表里、也不是 运行编号 / 状态 / 跑的版本 / 查结果",
                                       "改成登记过的参数名,或先在上面的参数表里加上它", node_id=n["id"], field_path="config.webhook_response.body"))
        elif any(((c.get(k) or {}).get("properties") if k != "webhook_response" else c.get(k)) for k in ("webhook_query_schema", "webhook_header_schema", "webhook_response")):
            出.append(问(警告, "WEBHOOK_CONFIG_UNUSED", f"开始方式是「{方式}」,网址参数 / 请求头参数 / 返回内容只对 Webhook 开头有用,现在不会用上",
                       "要么把开始方式改成 Webhook,要么把那几项清掉(留着不影响跑,但会让人以为生效了)", node_id=n["id"], field_path="config.webhook_response"))
        if 方式 != "定时":
            continue
        try:
            规则 = SCH.校验规则(c.get("schedule_rule") or {})
            # Cron 模式(11-21,规划 2-1)能写出比内置最密的「每小时」还密的频率(「* * * * *」一天 1440 次):每次到点都真跑、真花钱,
            # 不拦(Dify 也不拦),但要在检查里说出来 —— 24 这个数不是拍的,是可视化模式里能选到的最密档
            if 规则["周期"] == SCH.CRON and (次 := len(SCH.执行时刻们(规则, SCH.date(2026, 1, 1)))) > 24:
                出.append(问(警告, "START_TRIGGER_DENSE", f"这条 Cron 一天要跑 {次} 次,比内置最密的「每小时」还密 —— 每次到点都真跑生产那一版、真花一次钱",
                           "确认真要这么密;不是的话把「分」那一段改成一个固定值(比如 0)", node_id=n["id"], field_path="config.schedule_rule"))
        except SCH.规则不对 as e:
            出.append(问(阻断, "START_TRIGGER_RULE", f"「开始」的定时规则不对:{e}",
                       "在「开始」的「基本」里把多久跑一次、哪几天 / 几号、几点跑填对;Cron 模式写五段「分 时 日 月 周」", node_id=n["id"], field_path="config.schedule_rule"))
        多 = sorted(set(((c.get("input_schema") or {}).get("properties") or {})) - set(定时自填))
        if 多:
            出.append(问(阻断, "START_TRIGGER_EXCLUSIVE",
                       f"定时开头的流程不能再要使用者填东西({'、'.join(多)})—— 一条流程要么人点、要么定时跑(二选一)",
                       "把「使用者要提供什么」清空(定时只交给下一步「统计起」「统计止」两项),或把开始方式改回「用户输入」;两种都要就复制一条流程",
                       node_id=n["id"], field_path="config.input_schema"))

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
    # 入口是一张列表:循环 / 迭代一个(循环体端口),并行每条支路一个(支路端口 + 支路键;11-16)
    入口 = {None: [开始们[0]] if 开始们 else []}
    for 容器, ns in 按域.items():
        if 容器 is None:
            continue
        # 子图入口 = 容器节点经 循环体/支路 端口连到的那个(并行:每条支路一个)
        子入口 = [e.get("target") for e in 边们
                 if e.get("source") == 容器
                 and e.get("port") in (DS.循环体, DS.支路)
                 and 属于.get(e.get("target")) == 容器]
        是并行 = (按id.get(容器) or {}).get("type") == "parallel"
        if not 子入口:
            出.append(问(阻断, "SCOPE_NO_ENTRY",
                       "并行里面的步骤没有连上,跑到这里不知道先做哪一步" if 是并行 else "循环里面的步骤没有连上,跑到这里不知道先做哪一步",
                       "从每条支路的出口连一条线到那条支路的第一步" if 是并行 else "从这一步连一条线到循环里的第一步",
                       node_id=容器))
        入口[容器] = 子入口 if 是并行 else 子入口[:1]

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

    # 有界循环的设置(10-27):轮数上限 1–10、不许循环套循环(检查点只存一层循环帧)
    for n in 节点们:
        if n.get("type") != "loop":
            continue
        cfg = n.get("config") or {}
        上 = cfg.get("max_iterations")
        if 上 not in (None, "") and not (isinstance(上, int) and 1 <= 上 <= 10):
            出.append(问(阻断, "LOOP_MAX_RANGE", "循环最多跑几轮要填 1 到 10 之间的整数",
                       "在右侧「基本」里改「最多跑几轮」;要无人值守地多跑,先找技术管理员", node_id=n.get("id"),
                       field_path="config.max_iterations"))
        if n.get("container"):
            出.append(问(阻断, "LOOP_NESTED", "循环里面又放了一个循环,现在还不支持",
                       "把里面那个循环挪到外面,或者拆成两条流程", node_id=n.get("id")))

    # 列表迭代(11-12,照 Dify):配置形状 + 不许套娃 + 里面的步骤只能取「当前项 / 下标」——
    # 自己配置的形状查法和执行器同一份(runtime/列表迭代.py);要看整张图的几条在这里
    for n in 节点们:
        if n.get("type") != "foreach":
            continue
        i, cfg = n.get("id"), (n.get("config") or {})
        for code, 消息, 建议, fp in FE.配置问题(cfg):
            出.append(问(阻断, code, 消息, 建议, node_id=i, field_path=fp))
        if n.get("container"):
            # 检查点只存一层循环帧(和有界循环同一条);迭代套迭代 / 套循环,先不支持
            出.append(问(阻断, "FOREACH_NESTED", "迭代被放进了另一个循环 / 迭代里面,现在还不支持套着用",
                       "把它挪到外面;真要两层,拆成两条流程(外面那条逐项调用里面那条)", node_id=i))
        列 = (cfg.get("bindings") or {}).get("列表") if isinstance(cfg.get("bindings"), dict) else None
        t声 = _声明类型(列, 按id)
        if t声 is not None and t声 != "array":
            出.append(问(阻断, "FOREACH_NOT_LIST", f"「列表」选的那一项声明的类型是「{t声}」,不是列表 —— 没有可以逐项做的东西",
                       "在右侧「用到的数据」里给「列表」改选一个列表类型的结果(比如 列表操作 → 结果)",
                       node_id=i, field_path="config.bindings.列表"))
        o = cfg.get("item_output")
        if isinstance(o, dict) and o.get("source") == "node" and o.get("node_id"):
            m = 按id.get(o["node_id"])
            if m is None:
                出.append(问(阻断, "FOREACH_OUTPUT_NOT_FOUND", "「每一项交出什么」选的那一步已经被删掉了",
                           "在右侧「基本」里重新选迭代里面那一步的一项结果", node_id=i, field_path="config.item_output"))
            elif m.get("container") != i:
                出.append(问(阻断, "FOREACH_OUTPUT_NOT_INSIDE",
                           f"「每一项交出什么」选的是{_称(m)}的结果,它不在这个迭代里面 —— 每一项交出的东西要是这一项里面做出来的",
                           "在右侧「基本」里改选迭代里面那一步的一项结果", node_id=i, field_path="config.item_output"))
    for n in 节点们:
        容 = 按id.get(n.get("container") or "")
        if not 容 or 容.get("type") != "foreach":
            continue
        i, cfg = n.get("id"), (n.get("config") or {})
        if n.get("type") in ("loop", "foreach"):
            continue                                   # 套娃上面已经报了,不再报第二条
        报过 = set()
        # 「用到的数据」里取了被删掉的步骤,下面 ⑤ 报 BIND_NODE_NOT_FOUND;条件 / 赋值这些里面的引用没人查,在这里查
        绑定外 = {id(r) for r in FE.所有引用({k: v for k, v in cfg.items() if k != "bindings"})}
        for r in FE.所有引用(cfg):
            名 = FE.单项变量名(r)
            if 名 is not None and 名 not in FE.单项变量 and 名 not in 报过:
                报过.add(名)
                出.append(问(阻断, "FOREACH_SCOPE_UNKNOWN",
                           f"取的「{名 or '(没写名字)'}」不是迭代给的 —— 迭代里面只能取「当前项」和「下标」",
                           "在「用到的数据」里改选「迭代 · 当前项」或「迭代 · 下标」", node_id=i))
            if r.get("source") == "node" and r.get("node_id") == 容.get("id") and "self" not in 报过:
                报过.add("self")
                出.append(问(阻断, "FOREACH_SELF_REF",
                           f"取的是{_称(容)}自己的结果,可它要等所有项都做完才有 —— 这一项做的时候还取不到",
                           "要这一项的数据,改选「迭代 · 当前项」", node_id=i))
            if r.get("source") == "node" and r.get("node_id") not in 按id and id(r) in 绑定外:
                出.append(问(阻断, "FOREACH_REF_NOT_FOUND", "这一步取数的那一步已经被删掉了",
                           "在右侧重新选一个来源", node_id=i))

    可达, dom, 支路成员 = {}, {}, {}
    for 容器, ns in 按域.items():
        e0s = 入口.get(容器) or []
        e0 = e0s[0] if e0s else None
        全 = {n["id"] for n in ns if n.get("id")}
        # 并行(11-16):每条支路从自己的入口起各算一遍可达和支配,合起来就是这个作用域的;
        # 一个步骤同时从两条支路走得到 → 两条支路不独立(真并发时它跑几次、拿哪条的数都说不清),单独报
        r, d, 成员 = set(), {}, {}
        for h in e0s:
            rh = _可达(h, 后继) & 全
            成员[h] = rh
            r |= rh
            d.update(支配集(h, 后继, rh))
        可达[容器] = r
        dom[容器] = d
        支路成员[容器] = 成员
        if len(e0s) > 1:
            共 = sorted(set.intersection(*成员.values())) if 成员 else []
            for i in 共:
                出.append(问(阻断, "PARALLEL_BRANCH_SHARED",
                           f"{_称(按id[i])}同时连在两条支路后面 —— 支路之间要各走各的,一个步骤只能属于一条支路",
                           "把它只连在一条支路后面;两条支路都要用的东西,放到并行外面先做好", node_id=i))
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
        环 = next((c for c in (_找环(h, 后继, 成员.get(h, r)) for h in e0s) if c), None)
        if 环:
            出.append(问(阻断, "GRAPH_CYCLE",
                       f"有连线往回连,流程会绕圈停不下来:{' → '.join(_称(按id.get(x)) for x in 环)}",
                       "删掉往回连的那条线。确实要重复做的,用「有界循环」或「列表迭代」步骤,它们带次数上限",
                       node_id=环[-2] if len(环) > 1 else None))

    # ③½ 并行与汇总(11-16 一期;自己配置的形状查法在 runtime/并行.py,要看整张图的几条在这里)─────────
    并行跨支路已报 = set()     # (取数的步骤, 被取的步骤):⑤ 的支配检查对同一对会再报一条 BIND_MAYBE_MISSING,同一件事只说一次
    for n in 节点们:
        if n.get("type") != "parallel":
            continue
        i, cfg = n.get("id"), (n.get("config") or {})
        for code, 消息, 建议, fp in PL.配置问题(cfg):
            出.append(问(阻断, code, 消息, 建议, node_id=i, field_path=fp))
        if n.get("container"):
            出.append(问(阻断, "PARALLEL_NESTED", "并行被放进了循环 / 迭代 / 另一个并行里面,现在还不支持套着用",
                       "把它挪到外面;真要两层,拆成两条流程", node_id=i))
        键们 = PL.支路键们(cfg)
        出边 = [e for e in 边们 if e.get("source") == i and e.get("port") == DS.支路]
        出边键 = {str(e.get("branch_key")) for e in 出边 if e.get("branch_key") not in (None, "")}
        for k in 键们:
            if k not in 出边键:
                出.append(问(阻断, "PARALLEL_BRANCH_NO_EDGE", f"支路「{k}」没有连到它里面的第一步",
                           "从并行这一步「{k}」那个出口连一条线到这条支路的第一步;用不上就在「基本」里删掉这条支路".replace("{k}", k),
                           node_id=i, field_path=f"config.branches[{k}]"))
        for k in sorted(出边键 - set(键们)):
            出.append(问(阻断, "PARALLEL_EDGE_NO_BRANCH", f"有一条连线挂在支路「{k}」上,但「基本」里已经没有这条支路了",
                       "删掉这条线;还要这条支路的话,先在「基本」里把它加回来再连", node_id=i))
        for e in 出边:
            if e.get("target") in 按id and 属于.get(e.get("target")) != i:
                出.append(问(阻断, "PARALLEL_BRANCH_NOT_INSIDE",
                           f"支路「{e.get('branch_key')}」连到的{_称(按id[e['target']])}不在这个并行里面",
                           "在那一步的「高级」里把它放进这个并行,或者改连到并行里面的步骤", node_id=i,
                           edge=f"{i} --{DS.支路}--> {e.get('target')}"))
        # 支路之间互不引用:独立状态命名空间(规格 §6.3)。成员按从各支路入口走得到算
        成员 = 支路成员.get(i) or {}
        属哪条 = {}
        for h, rs in 成员.items():
            for x in rs:
                属哪条.setdefault(x, h)
        for m in 节点们:
            if m.get("container") != i:
                continue
            if m.get("type") in ("loop", "foreach", "parallel"):
                出.append(问(阻断, "PARALLEL_NESTED", f"{_称(m)}被放进了并行里面,现在还不支持并行里套循环 / 迭代 / 并行",
                           "把它挪到并行外面;真要的话拆成两条流程", node_id=m.get("id")))
            我 = 属哪条.get(m.get("id"))
            for r in FE.所有引用(m.get("config") or {}):
                x = r.get("node_id") if r.get("source") == "node" else None
                if x and x in 按id and 属于.get(x) == i and 我 is not None and 属哪条.get(x) not in (None, 我):
                    并行跨支路已报.add((m.get("id"), x))
                    出.append(问(阻断, "PARALLEL_CROSS_BRANCH",
                               f"{_称(m)}取了另一条支路里{_称(按id[x])}的结果 —— 支路之间各走各的,谁先做完不一定",
                               "两条支路都要用的东西放到并行外面先做好;要用另一条支路的结果,等并行做完从它的「结果」里取",
                               node_id=m.get("id")))
                    break

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
        # 每一路至少一条条件、每条选了取哪个值(10-27 一路可以几条):空的一路按「且」算会永远满足
        for b in (cfg.get("branches") or []):
            if not isinstance(b, dict):
                continue
            条们, _ = DS.分支条件(b)
            if not 条们:
                出.append(问(阻断, "COND_EMPTY", f"「{b.get('key')}」这一路一条条件都没有 —— 空条件不会当成始终满足",
                           "在右侧「基本」里给这一路加一条条件,用不上就删掉这一路",
                           node_id=i, field_path=f"config.branches[{b.get('key')}]"))
            for j, w in enumerate(条们, 1):
                if not w.get("op") or not isinstance(w.get("left"), dict):
                    出.append(问(阻断, "COND_INCOMPLETE",
                               f"「{b.get('key')}」这一路第 {j} 条条件还没选「取哪个值」或「怎么比」",
                               "在右侧「基本」里把这条条件填完,或者删掉它",
                               node_id=i, field_path=f"config.branches[{b.get('key')}].conditions[{j}]"))
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

    # ④b 问题分类器:类别至少两个、名字不重复、每个类别连了线(10-27)──────────
    for n in 节点们:
        if n.get("type") != "classifier":
            continue
        i = n.get("id")
        类们 = (n.get("config") or {}).get("classes")
        if 类们 in (None, "", [], {}):
            continue                       # 必填那条已经报了
        名们 = [str((c or {}).get("key") or "").strip() for c in 类们 if isinstance(c, dict)]
        if len([x for x in 名们 if x]) < 2:
            出.append(问(阻断, "CLASSIFY_TOO_FEW", "类别不到两个,没什么可分的",
                       "在右侧「基本」里至少写两个类别", node_id=i, field_path="config.classes"))
        if "" in 名们:
            出.append(问(阻断, "CLASSIFY_NO_NAME", "有一个类别没起名字 —— 名字就是交给模型的选项,也是出口名",
                       "在右侧「基本」里给它起个名字,用不上就删掉", node_id=i, field_path="config.classes"))
        for k in sorted({x for x in 名们 if x and 名们.count(x) > 1}):
            出.append(问(阻断, "CLASSIFY_DUP", f"类别「{k}」写了两次,模型答它时不知道走哪一路",
                       "删掉一个,或者改个名字", node_id=i, field_path="config.classes"))
        出边键 = {e.get("branch_key") for e in 边们 if e.get("source") == i and e.get("port") == DS.分支}
        for k in sorted(set(x for x in 名们 if x) - 出边键):
            出.append(问(阻断, "CLASSIFY_NO_EDGE", f"「{k}」这一类没有连到下一步 —— 模型分到这一类时流程就停在这里",
                       "从这一类的出口连一条线到下一步;用不上就删掉这个类别", node_id=i, field_path=f"config.classes[{k}]"))
        for k in sorted(出边键 - set(名们) - {None}):
            出.append(问(阻断, "CLASSIFY_EDGE_NO_CLASS", f"有一条连线挂在「{k}」这一类上,但类别里已经没有它了",
                       "删掉这条线;还要这一类的话,先在「基本」里加回来再连", node_id=i))

    # ④c 参数提取器:名字不空、不重复、类型认得(10-27)──────────────────────
    for n in 节点们:
        if n.get("type") != "extractor":
            continue
        i = n.get("id")
        参们 = (n.get("config") or {}).get("parameters")
        if 参们 in (None, "", [], {}):
            continue                       # 必填那条已经报了
        名们 = [str((p or {}).get("name") or "").strip() for p in 参们 if isinstance(p, dict)]
        if "" in 名们:
            出.append(问(阻断, "EXTRACT_NO_NAME", "有一项参数没起名字 —— 后面的步骤按名字取它",
                       "在右侧「基本」里给它起个名字,用不上就删掉", node_id=i, field_path="config.parameters"))
        for k in sorted({x for x in 名们 if x and 名们.count(x) > 1}):
            出.append(问(阻断, "EXTRACT_DUP", f"参数「{k}」写了两次,后面取它时不知道是哪一个",
                       "删掉一个,或者改个名字", node_id=i, field_path="config.parameters"))
        for p in 参们:
            if isinstance(p, dict) and (p.get("type") or "string") not in DS.参数类型中文:
                出.append(问(阻断, "EXTRACT_BAD_TYPE", f"参数「{p.get('name')}」的类型系统不认识",
                           f"在右侧「基本」里重新选类型(可选:{'、'.join(DS.参数类型中文.values())})",
                           node_id=i, field_path="config.parameters"))

    # ④d 变量赋值:在循环里、改的是那个循环声明过的状态、不和「每一轮结束取自」抢着写(10-27)────
    for n in 节点们:
        if n.get("type") != "assigner":
            continue
        i, 容 = n.get("id"), 按id.get(n.get("container") or "")
        if not 容 or 容.get("type") != "loop":
            出.append(问(阻断, "ASSIGN_NOT_IN_LOOP", "变量赋值现在只能放在循环里 —— 它改的是循环状态",
                       "在右侧「放在哪个循环里」选一个循环;会话变量等对话流那一期", node_id=i))
            continue
        声明 = (容.get("config") or {}).get("loop_state") or {}
        for j, a in enumerate((n.get("config") or {}).get("assignments") or [], 1):
            a = a if isinstance(a, dict) else {}
            k, 法, fp = a.get("variable"), a.get("op"), f"config.assignments[{j}]"
            if k not in 声明:
                出.append(问(阻断, "ASSIGN_UNKNOWN_VAR", f"第 {j} 条要改的「{k or '(没选)'}」不是{_称(容)}的循环状态",
                           "在右侧选循环状态里的一项;要的那项还没有,先去循环的设置里加", node_id=i, field_path=fp))
                continue
            if 法 not in DS.赋值改法:
                出.append(问(阻断, "ASSIGN_BAD_OP", f"第 {j} 条还没选怎么改", "在右侧选:覆盖 / 加上 / 追加 / 清空",
                           node_id=i, field_path=fp))
            elif 法 in ("set", "append") and not isinstance(a.get("value"), dict):
                出.append(问(阻断, "ASSIGN_NO_VALUE", f"第 {j} 条「{DS.赋值改法[法]}」还没选值从哪来", "在右侧给它选来源或填一个固定值",
                           node_id=i, field_path=fp))
            elif 法 == "add" and not DS.类型对吗((a.get("value") or {}).get("value") if isinstance(a.get("value"), dict) else a.get("value"), "number"):
                出.append(问(阻断, "ASSIGN_ADD_NOT_NUMBER", f"第 {j} 条「加上」后面要填一个数字", "填一个数字,比如 1",
                           node_id=i, field_path=fp))
            if isinstance(声明.get(k), dict) and 声明[k].get("update"):
                出.append(问(阻断, "ASSIGN_CONFLICT_UPDATE",
                           f"「{k}」在循环设置里已经是「每一轮结束取自某一步」,这一步又改它 —— 两个写的人,最后算谁的取决于走到哪",
                           f"二选一:去掉循环设置里「{k}」的「每一轮结束取自」,或者删掉这一条", node_id=i, field_path=fp))

    # ④e 列表操作 / 文档提取器(11-12,照 Dify):规则的形状在校验期就拦 —— 查法和执行器同一份(runtime/列表操作.py、文档提取.py)
    for n in 节点们:
        t, i, cfg = n.get("type"), n.get("id"), (n.get("config") or {})
        if t == "list_operator":
            for code, 消息, 建议, fp in LO.配置问题(cfg):
                出.append(问(阻断, code, 消息, 建议, node_id=i, field_path=fp))
        elif t == "doc_extractor":
            绑 = cfg.get("bindings") if isinstance(cfg.get("bindings"), dict) else {}
            if 绑 and "文件" not in 绑:
                出.append(问(阻断, "DOC_NO_INPUT", "还没选从哪个文件取文字",
                           "在右侧「用到的数据」里给「文件」选上传文件的那一项", node_id=i, field_path="config.bindings.文件"))
            for k in sorted(set(绑) - {"文件"}):
                出.append(问(阻断, "DOC_EXTRA_BINDING", f"「用到的数据」里多了一项「{k}」,文档提取器只用「文件」那一项,它不会被读",
                           f"删掉「{k}」", node_id=i, field_path=f"config.bindings.{k}"))
            if isinstance(绑.get("文件"), dict) and 绑["文件"].get("source") == "constant":
                v = 绑["文件"].get("value")
                try:
                    DE.引用们(v)
                except DE.做不了 as e:
                    出.append(问(阻断, e.code, e.消息, e.建议, node_id=i, field_path="config.bindings.文件"))

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
            if not 来源["进模型上下文"] and t in ("llm", "agent", "classifier", "extractor"):
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
            if 属于.get(m) != 域:
                # 循环体里引用循环外面的一步(10-27):不在同一个作用域里比支配 —— 改问「那一步是不是一定在**这个循环**之前跑」
                容 = 域
                while 容 is not None and 属于.get(容) != 属于.get(m):
                    容 = 属于.get(容)
                外 = dom.get(属于.get(m), {})
                if 容 is not None and 容 in 外 and m not in 外[容]:
                    出.append(问(阻断, "BIND_MAYBE_MISSING",
                               f"「{字段}」取的是{_称(按id[m])}的结果,但走另一条分支时它不会执行,到循环这里就取不到值",
                               "在分支之后加一个「分支汇合」,把几条分支的结果并成一项,再从汇合那一步取",
                               node_id=i, field_path=fp))
                continue
            if m == i:
                出.append(问(阻断, "BIND_SELF",
                           f"「{字段}」取的是这一步自己的结果,可这一步还没跑完",
                           f"在右侧「用到的数据」里给「{字段}」改选前面某一步的结果",
                           node_id=i, field_path=fp))
            elif (i, m) in 并行跨支路已报:
                continue                      # 跨支路取数,③½ 已经按并行的话说过了
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

    # ⑤¾ HTTP 请求节点(三期 3-1):方法只开读、路径得有、连接得在 —— 判据本体在 runtime/出网策略.py,这里只核配置
    # (11-20 修:这里原来 node_id=i 写的是列表序号不是节点 id,前端按 node_id 找节点标红永远找不到 —— 报出来却没人看得见是哪一步)
    for i, n in enumerate(节点们):
        if n.get("type") != "http_request":
            continue
        cfg = n.get("config") or {}
        方法 = str(cfg.get("method") or "GET").upper()
        if 方法 not in ("GET", "HEAD"):
            出.append(问(阻断, "HTTP_METHOD_NOT_ALLOWED",
                       f"这一步想用 {方法} —— HTTP 请求一期只开「读」(GET / HEAD),写入(POST / PUT / PATCH / DELETE)要等二期",
                       "把方法改成 GET 或 HEAD;要往外写数据,先用业务动作步骤", node_id=n.get("id"), field_path="config.method"))
        有路径 = isinstance(cfg.get("path"), str) and cfg.get("path").strip() != "" or "path" in (cfg.get("bindings") or {})
        if not 有路径:
            出.append(问(阻断, "HTTP_PATH_MISSING", "还没写请求哪个路径",
                       "在右侧「基本」里填路径(相对连接白名单的,如 /stock),或在「用到的数据」里把 path 绑到前面某一步的结果",
                       node_id=n.get("id"), field_path="config.path"))
        cid = cfg.get("connection_id")
        if cid and 依赖存在 is not None and not 依赖存在("connection_id", cid):
            出.append(问(阻断, "REF_NOT_FOUND", "选的工具连接已经用不了:被删了、归档了,或者不在这个项目里",
                       "在右侧「基本」里重新选一条工具连接", node_id=n.get("id"), field_path="config.connection_id"))

    # ⑤⅞ 知识检索节点(三期 3-5,11-20 做通):要查什么得绑上;选了资料库但没有就绪的索引要说出来(不在没建好的索引上检索)
    for i, n in enumerate(节点们):
        if n.get("type") != "retrieve":
            continue
        cfg = n.get("config") or {}
        绑 = cfg.get("bindings") or {}
        if not isinstance(绑.get("问题"), dict) or not 绑.get("问题"):
            出.append(问(阻断, "RETRIEVE_QUERY_MISSING", "还没说要查什么",
                       "在右侧「用到的数据」里把「问题」绑到开始的某一项,或前面某一步产出的文本", node_id=n.get("id"), field_path="config.bindings.问题"))
        if cfg.get("knowledge_base_id") and not cfg.get("index_build_id"):
            出.append(问(阻断, "RETRIEVE_NO_READY_INDEX", "选的资料库还没有「已就绪」的索引,查不了",
                       "先到「知识库」页给这个资料库建一次索引,回来重新选它;不在没建好的索引上检索 —— 结果会不完整,而那和「库里就这么点」长得一样",
                       node_id=n.get("id"), field_path="config.index_build_id"))

    # ⑤⅞⁺⁺ 代码执行(三期 3-4 最小版,11-20):判据本体在 runtime/代码执行.配置问题(代码非空 / 只 Python / 声明了结果 / 上限不许超 5 秒 64 MB / 变量名合法)
    for n in 节点们:
        if n.get("type") != "code":
            continue
        import 代码执行 as _CODE
        for code, 消息, 建议, fp in _CODE.配置问题(n.get("config") or {}):
            if code == "CODE_EMPTY" and "code" in (DS.找节点("code")["必填"]):
                continue   # 必填那条已经按 字段提示 报过「还没写代码」,别报两遍
            出.append(问(阻断, code, 消息, 建议, node_id=n.get("id"), field_path=fp))

    # ⑤⅞⁺ 人工介入表单化(四期 4-1,11-20 照 Dify):按钮 id 唯一非空、分支线的 key 要是某个按钮、按钮没接线提醒;字段名唯一非空;说明里 {{x}} 要是材料里有的
    for n in 节点们:
        if n.get("type") != "human":
            continue
        i, cfg = n.get("id"), (n.get("config") or {})
        按钮 = cfg.get("actions") or []
        键们 = []
        for k, a in enumerate(按钮 if isinstance(按钮, list) else []):
            aid = (a or {}).get("id") if isinstance(a, dict) else None
            if not aid or not str(aid).strip():
                出.append(问(阻断, "HUMAN_ACTION_KEY", f"第 {k + 1} 个按钮没有标识", "给每个按钮一个标识(比如 顾客责任),它就是这一路出口的名字", node_id=i, field_path=f"config.actions[{k}]"))
            elif aid in 键们:
                出.append(问(阻断, "HUMAN_ACTION_KEY", f"两个按钮都叫「{aid}」—— 走哪一路分不清", "改掉其中一个的标识", node_id=i, field_path=f"config.actions[{k}]"))
            else:
                键们.append(aid)
        分支线 = [e for e in 边们 if e.get("source") == i and e.get("port") == DS.分支]
        for e in 分支线:
            if e.get("branch_key") not in 键们:
                出.append(问(阻断, "HUMAN_EDGE_NO_ACTION", f"有一条线挂在按钮「{e.get('branch_key')}」上,但「基本」里没有这个按钮",
                           "删掉这条线;还要这一路的话,先在「基本」里把按钮加回来再连", node_id=i, edge=f"{i} --{DS.分支}--> {e.get('target')}"))
        for aid in 键们:
            if not any(e.get("branch_key") == aid for e in 分支线):
                出.append(问(警告, "HUMAN_ACTION_UNWIRED", f"按钮「{aid}」还没接线 —— 人点了它这次运行就在这里结束",
                           "从这一步「{k}」那个出口拖一条线到下一步;用不上就在「基本」里删掉这个按钮".replace("{k}", aid), node_id=i))
        名们 = set()
        for k, f in enumerate(cfg.get("form_fields") or []):
            名 = (f or {}).get("name") if isinstance(f, dict) else None
            if not 名 or not str(名).strip() or 名 in 名们:
                出.append(问(阻断, "HUMAN_FIELD_KEY", f"第 {k + 1} 个表单字段{'重名' if 名 in 名们 else '没有名字'}", "每个字段一个不重复的名字,下游按它取值", node_id=i, field_path=f"config.form_fields[{k}]"))
            名们.add(名)
            if (f or {}).get("type") == "下拉" and not ((f or {}).get("options") or []):
                出.append(问(阻断, "HUMAN_FIELD_OPTIONS", f"下拉字段「{名}」一个选项都没有", "填上可选项,或把类型改成「段落」", node_id=i, field_path=f"config.form_fields[{k}].options"))
        说明 = cfg.get("form_markdown") or ""
        if 说明:
            import re as _re2
            材料键 = set((cfg.get("payload_binding") or {}).keys())
            for 名 in sorted(set(_re2.findall(r"\{\{\s*([^{}\s]+)\s*\}\}", 说明))):
                if 名 not in 材料键:
                    出.append(问(警告, "HUMAN_FORM_REF", f"说明里引用了「{名}」,但「用到的数据」里没有这一项 —— 核对的人会看到一个空",
                               "在「用到的数据」里加上它,或改掉说明里的名字", node_id=i, field_path="config.form_markdown"))

    # ⑥ 依赖引用:存在、同项目、有权限 —— 由调用方提供查询能力 ────────
    引用字段 = {"connection_version_id": "连接版本", "prompt_version_id": "Prompt 版本",
              "tool_version_id": "工具版本", "agent_version_id": "Agent 版本",
              "knowledge_base_id": "知识库", "index_build_id": "索引构建",
              "retrieval_config_version_id": "检索配置版本",
              "workflow_version_id": "工作流版本",
              "notify_connection_id": "通知连接",   # 11-20 人工介入到这一步推飞书通知用的工具连接(四期 4-1)
              # 11-06:整条工作流选一版术语,挂在**开始节点**的配置上(冻结版本只存节点 / 连线 / 输入输出,
              # 顶层字段冻结时会丢;开始节点跟着节点一起冻、一起进逻辑哈希 —— 换术语版本 = 改了流程,发生产要重新跑通)
              "glossary_version_id": "术语版本"}
    # ⚠️ 这张表是「引用别的资源的字段」—— 开始节点的 start_mode / schedule_rule 不是引用,别往里加
    #    (11-16 加过一次,结果 REF_NOT_FOUND 把「开始方式」当成被删的资源报了一条)
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

    # ⑥½ 子工作流(11-16 三期 3-3 一期;规则在 runtime/子工作流.py):只引冻结版、静态禁递归、深度上限、
    #     子流程里不许有停下等人 / 等外部的步骤、交给它的输入要齐 ────────────────────────────
    取版本 = getattr(依赖存在, "取版本", None)
    工具读写 = getattr(依赖存在, "工具读写", None)
    本工作流 = getattr(依赖存在, "本工作流", None)
    for n in 节点们:
        if n.get("type") != "subworkflow":
            continue
        i, cfg = n.get("id"), (n.get("config") or {})
        for code, 消息, 建议, fp in SW.配置问题(cfg):
            出.append(问(阻断, code, 消息, 建议, node_id=i, field_path=fp))
        vid = cfg.get("workflow_version_id")
        if not vid or not isinstance(vid, str):
            continue
        if 取版本 is None:
            if "子流程引的那一版还在不在、有没有绕回来引自己(这次没给查询能力)—— 这不算通过,是没查" not in 跳过:
                跳过.append("子流程引的那一版还在不在、有没有绕回来引自己(这次没给查询能力)—— 这不算通过,是没查")
            continue
        子 = 取版本(vid)
        if not 子:
            continue                       # 不存在由 ⑥ REF_NOT_FOUND 报
        码, 深, 路 = SW.递归链(vid, 取版本, 本工作流=本工作流)
        if 码 == "SUBWORKFLOW_RECURSION":
            出.append(问(阻断, 码, "子流程绕回来引了这条流程自己(或链上同一条流程出现两次),跑起来没有尽头",
                       "换一版不引回来的子流程;要重复做的用「有界循环」或「列表迭代」", node_id=i, field_path="config.workflow_version_id"))
        elif 码 == "SUBWORKFLOW_TOO_DEEP":
            出.append(问(阻断, 码, f"子流程套得太深(超过 {SW.深度上限} 层:这条 → 子 → 孙 …)",
                       "把最里面那层拆出来直接放进这条流程,或者少套一层", node_id=i, field_path="config.workflow_version_id"))
        for nid, 为 in SW.不能等的步骤(子, 工具读写):
            出.append(问(阻断, "SUBWORKFLOW_WAIT_UNSUPPORTED",
                       f"引的子流程里有会停下来等的步骤({为}「{nid}」)—— 一期子流程在这一步里同步跑完,没有自己的检查点,等不了",
                       "把那一步挪到这条流程里来(等人的事由父流程停),或换一版没有它的子流程", node_id=i, field_path="config.workflow_version_id"))
        入 = DS.入参结构(子)
        映 = cfg.get("input_mapping") if isinstance(cfg.get("input_mapping"), dict) else {}
        缺 = sorted(set(入.get("required") or []) - set(映))
        if 缺:
            出.append(问(阻断, "SUBWORKFLOW_INPUT_MISSING", f"子流程要的输入还没给:{'、'.join(缺)}",
                       "在右侧「用到的数据」里给每一项选来源", node_id=i, field_path="config.input_mapping"))
        多 = sorted(set(映) - set((入.get("properties") or {}).keys())) if 入.get("properties") is not None else []
        if 多:
            出.append(问(警告, "SUBWORKFLOW_INPUT_UNKNOWN", f"交给子流程的这几项它不收:{'、'.join(多)}(会被忽略)",
                       "删掉用不上的那几项", node_id=i, field_path="config.input_mapping"))

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
    # 读结束节点里那份,不读顶层(11-16:顶层是建模板时抄的、没人同步 —— 编辑器改了结束节点的字段,这里还按老字段要来源)
    输出 = DS.出参结构(定义)
    必需 = set(输出.get("required") or [])
    for i in 结束们:
        绑 = ((按id[i].get("config") or {}).get("bindings") or {})
        # 「返回成功」和「任务达标」是两件事(§6.1),而缺一个必需字段连前者都不成立
        for f in sorted(必需 - set(绑)):
            出.append(问(阻断, "END_MISSING_OUTPUT",
                       f"最后要返回「{f}」,但还没选它从哪来",
                       f"在右侧「用到的数据」里给「{f}」选一个前面步骤的结果", node_id=i,
                       field_path=f"config.bindings.{f}"))

    # ⑨ 直接回复:模板里每个名字都要在「用到的数据」里有一项(10-27)───────────
    # 不查的话,手写的 {{单号}} 运行到这一步才失败 —— 而那时前面的模型钱已经花了
    # 模板转换(10-27)同一条:它的模板没人看着发出去,但下游拿到带花括号的一段字,照样当成真内容往下用
    for n in 节点们:
        if n.get("type") not in ("answer", "template"):
            continue
        cfg = n.get("config") or {}
        绑 = cfg.get("bindings") or {}
        回 = n.get("type") == "answer"
        for k in DS.回复占位名(cfg.get("template")):
            if k not in 绑:
                出.append(问(阻断, "ANSWER_PLACEHOLDER_UNBOUND" if 回 else "TEMPLATE_PLACEHOLDER_UNBOUND",
                           f"{'回复' if 回 else '模板'}里写了「{{{{{k}}}}}」,但「用到的数据」里没有叫「{k}」的一项 —— 运行时会原样发出花括号",
                           f"在右侧「用到的数据」里加一项叫「{k}」并选来源,或者把模板里的这个名字删掉",
                           node_id=n.get("id"), field_path="config.template"))

    _读写 = getattr(依赖存在, "工具读写", None) if 依赖存在 is not None else None

    # ⑨½ Webhook 开头的流程:写数据的业务动作前面必须有人工介入(工作流二期 2-2,规划 11-15 拍)──
    # Webhook 是外部系统按一把密钥叫起来的,没有人在场 —— 让它直接写数据,等于把写口交给了密钥持有方。
    # 判「前面有人」用支配集:从开始到这一步的**每一条**路都必经一个人工介入才算;只在某一条分支上有人不算。
    # 在循环 / 并行 / 子容器里的步骤,容器里没人就往外一层看「容器本身前面有没有人」。
    if any(n.get("type") == "start" and (n.get("config") or {}).get("start_mode") == "Webhook" for n in 节点们):
        def _前面有人(i):
            当前 = i
            while True:
                域 = 属于.get(当前)
                d = dom.get(域, {}).get(当前)
                if d is None:
                    return None          # 走不到的步骤由连线那一段报,这里不重复
                if any((按id.get(m) or {}).get("type") == "human" for m in d - {当前}):
                    return True
                if 域 is None:
                    return False
                当前 = 域
        for n in 节点们:
            i = n.get("id")
            if n.get("type") != "tool" or not i:
                continue
            if _读写 is None:
                跳过.append("Webhook 开头的流程里业务动作是不是只读(这次没给查询能力)—— 这不算通过,是没查")
                break
            tv = (n.get("config") or {}).get("tool_version_id")
            if (_读写(tv) if tv else None) == "read_only":
                continue
            if _前面有人(i) is False:
                出.append(问(阻断, "WEBHOOK_WRITE_NEEDS_HUMAN",
                           f"{_称(n)}会写数据(或者还查不到它的读写登记),而这条流程是 Webhook 叫起来的 —— 没有人在场,"
                           "外部系统一调就直接写了",
                           "在它前面加一个「人工介入」(每条走到它的路上都要经过),让人核对后再写;只是查数据就换成只读的业务动作",
                           node_id=i))

    # ⑩ 失败后怎么办(工作流一期第二件,11-15;照 Dify「异常处理」)───────────────
    # 面板上选了一种失败后的走法,运行时必须真照着走 —— 选了「走失败线」却没接线、
    # 选了「按默认值继续」却没填默认值,运行时都会悄悄退回「整次运行失败」,而面板上看着已经配好了。
    for n in 节点们:
        t, i = n.get("type"), n.get("id")
        cfg = n.get("config") or {}
        策 = cfg.get("failure_policy")
        try:
            元 = DS.找节点(t)
        except KeyError:
            continue
        if "default_output" in cfg and 策 != "default":
            出.append(问(警告, "FAILURE_DEFAULT_UNUSED", "这一步填了出错时的默认值,但失败后的走法不是「按默认值继续」,默认值不会生效",
                       "在右侧「高级」里把「失败后怎么办」改成「按默认值继续」,或者把默认值清空",
                       node_id=i, field_path="config.default_output"))
        if 策 is None:
            continue
        if DS.失败 not in 元["端口"]:
            出.append(问(阻断, "FAILURE_POLICY_INAPPLICABLE", f"「{元['中文']}」这类步骤没有失败后的走法可选,这项设置不会生效",
                       "在右侧「高级」里把它清空", node_id=i, field_path="config.failure_policy"))
            continue
        if 策 not in DS.失败策略们:
            出.append(问(阻断, "FAILURE_POLICY_UNKNOWN", "失败后怎么办选了一个系统不认识的走法",
                       f"在右侧「高级」里重新选:{' / '.join(DS.失败策略们.values())}",
                       node_id=i, field_path="config.failure_policy"))
            continue
        if 策 == "branch" and not any(e.get("source") == i and e.get("port") == DS.失败 for e in 边们):
            出.append(问(警告, "FAILURE_BRANCH_NO_EDGE", "选了失败后「走『失败时』那条线」,但这一步的「失败时」出口没接任何步骤 —— 真失败时整次运行会失败",
                       "从这一步的「失败时」出口拉一条线到处理失败的步骤;不想单独处理就改成「这次运行失败」",
                       node_id=i, field_path="config.failure_policy"))
        if 策 != "default":
            continue
        if t not in DS.默认值可用的类型:
            出.append(问(阻断, "FAILURE_DEFAULT_NOT_ALLOWED",
                       f"「{元['中文']}」这类步骤不能「按默认值继续」:它失败时假装成功往下走,后面的步骤会照着一个没发生的结果做事",
                       "改成「这次运行失败」或「走『失败时』那条线」", node_id=i, field_path="config.failure_policy"))
            continue
        if t == "tool":
            # 用户 11-15 拍:写数据的业务动作失败了不许按默认值继续 —— 后面可能照着「券已发」去通知顾客
            tv = cfg.get("tool_version_id")
            if _读写 is None:
                跳过.append("按默认值继续的业务动作是不是只读(这次没给查询能力)—— 这不算通过,是没查")
            else:
                读写 = _读写(tv) if tv else None
                if 读写 != "read_only":
                    出.append(问(阻断, "FAILURE_DEFAULT_ON_WRITE",
                               "这个业务动作会写数据(或者还查不到它的读写登记),失败了不能「按默认值继续」:"
                               "比如发券失败却当成发了,后面会照着「券已发」去通知顾客",
                               "改成「这次运行失败」或「走『失败时』那条线」,在失败线上安排人工处理",
                               node_id=i, field_path="config.failure_policy"))
                    continue
        默 = cfg.get("default_output")
        if not isinstance(默, dict) or not 默:
            出.append(问(阻断, "FAILURE_DEFAULT_MISSING", "选了「按默认值继续」,但还没填出错时交出什么",
                       "在右侧「高级」里把默认值填上:后面步骤要用的每一项都给一个值",
                       node_id=i, field_path="config.default_output"))
            continue
        要 = set(((cfg.get("output_schema") or {}).get("required")) or [])
        缺 = sorted(要 - set(默))
        if 缺:
            出.append(问(阻断, "FAILURE_DEFAULT_INCOMPLETE",
                       f"出错时的默认值缺了这几项:{'、'.join(缺)} —— 后面步骤取它们时会取不到",
                       "在右侧「高级」里把这几项的默认值补上", node_id=i, field_path="config.default_output"))
        保留 = sorted({"error_type", "error_message"} & set(默))
        if 保留:
            出.append(问(阻断, "FAILURE_DEFAULT_RESERVED",
                       f"默认值里不能自己填 {'、'.join(保留)}:这两项由系统在出错时写上真实的错误",
                       "把这几项从默认值里删掉", node_id=i, field_path="config.default_output"))

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
        # glossary_version_id(11-06 深夜补):选了一个不存在的术语版本,原来校验 / 冻结都放行,到运行时才 GLOSSARY_VERSION_NOT_FOUND
        for f in ("connection_version_id", "prompt_version_id", "glossary_version_id"):
            v = 配置.get(f)
            if v and not 依赖存在(f, v):
                出.append(问(阻断, "REF_NOT_FOUND",
                           f"{f} = {v} 不存在、无权访问或已撤回",
                           "换一个当前项目里有权访问的版本" + ("(术语要选「术语配置」里冻结过的版本)" if f == "glossary_version_id" else ""),
                           field_path=f))
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
        if 要工具 and "原生工具调用" in 能力 and 能力["原生工具调用"] is None:
            # 11-06 探测存三值:**探过这一项、但没判出来**(端点的回话不在已知的几种里 —— 比如对方改了错误文案)。
            # 和「判出来不支持」下一步不同:那个该换连接,这个该看原话、重探或人工确认。
            # 照样阻断(未知不等于支持),只是不许和「不支持」长成同一句话 —— 不然文案一改,降级会被静默走上
            出.append(问(阻断, "MODEL_TOOL_CALLING_UNKNOWN",
                       "这个模型连接**探过「原生工具调用」,但没判出来**支不支持"
                       f"(探测时端点的原话:{str(能力.get('原生工具调用怎么判的') or '')[:120]})",
                       "先看那句原话:端点可能改了错误文案,或者这次探测时网络 / 凭据不对。重探一次;"
                       "还判不出来就请技术管理员人工确认,再更新探测的判读(connections_api.判工具调用)",
                       field_path="connection_version_id"))
        elif 要工具 and not 能力.get("原生工具调用"):
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
