#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一份草稿**冻成一版策略** —— 纯逻辑,零 IO。规格 §4.2 / §10.2 / §5.3。

## 它在链路里的位置

规格 §4.2 的四个状态,这是第 ① → ② 那一步:

    草稿已保存  ──冻结──▶  版本已发布  ──回执──▶  实例已加载  ──▶  本次运行已采用
                 ↑ 这儿                              `策略解析.py` 管后面三个

## 为什么要有「冻结」这一步,而不是直接发布草稿

规格 §4.2 的表第一行写得很直接:「草稿已保存」**不能表示门店已生效**。
而冻结的意义是**把内容钉死并算出哈希** —— 有了哈希,后面三件事才成立:

    · 实例回执时能核「你加载的是不是这一版」(§10.3 服务端核验身份)
    · 页面能回答「这一版和上一版内容变了吗」
    · Run 上记下的快照能被第三方重算

> **一个没有哈希的「版本」,和一份草稿,在能证明的事情上长得一模一样。**

## 哈希用的是**缓存那边同一个规范化器**

`cache/key_builder.规范化()` —— **不另写一套**。

为什么不用 `json.dumps(sort_keys=True)`:策略的 `limits` 里
`{"tool_timeout_seconds": 0}` 和 `{..: null}` 是两件事(「不等待」vs「没设」),
而某些写法会把 `""` 和 `None` 折成同一个串。

> **一个把 `0` 和 `null` 折成同一个字符串的哈希,和一个真区分了的,
> 在那个哈希值上长得一模一样** —— 而两版内容不同的策略会因此拿到同一个版本号,
> 于是「这一版变了吗」永远回答「没变」。

而 `_规范` 还有一条要紧的性质:**只排对象的键,不动数组顺序**。
`support_conditions` 是个数组,而它的顺序**不该**影响哈希 ——
所以这里在算之前**自己把它排好**(见 `_要算进哈希的`),
而不是去改那个规范化器的行为。

## 五条判据

### ① 哈希只覆盖**影响行为的那些字段**,而那份清单是显式的

不是「把整个草稿 dump 一遍」。草稿里有 `owner` / `change_note` /
`draft_revision` 这些**不影响执行**的字段 —— 把它们算进去,
改一句备注就会得到一个「新版本」,而那一版和旧版**行为一模一样**。
> 一个因为改了备注而冒出来的新版本,和一个真的改了限制的,
> **在版本列表上长得一模一样**。

### ② 冻结前**校验形状**,而且不替它填默认值

规格 §5.3:「次数/秒数必须是正整数;重试允许 0;**布尔值不能作为数字**」。
一个 `{"tool_attempt_cap": true}` 的 limits 冻进去之后,
执行层读到 `True`,而 Python 里 `True == 1` ——
> **一条上限 1 次的策略,和一条写着 `true` 的,在执行时长得一模一样**,
> 而填的人以为自己打开了这个保护。

### ③ `support_conditions` 必须是 `limits` 里**真有的那些键**

它说的是「这一版要求执行入口支持哪些限制」。要求一个 `limits` 里
根本没填的限制,等于要求实例支持一个不存在的东西 ——
而 `策略解析.py` 会拿它去核能力,于是**永远拒绝启动**,
且报错指向「实例不支持」而不是「策略写错了」。
> 一句解释错了东西的报错,比不解释更误导人。

### ④ 版本号由**调用方给**,而且必须比上一版大

这里不猜版本号(它要查库)。但**给了就要校验** ——
规格里「版本号唯一且密集」是一堆地方隐含依赖的不变量
(`uq_execution_policy_versions_pi_ai_ek_vn` 就是它的落点)。

### ⑤ 入口要点名,**和迁移里的 CHECK 约束同一套字面量**

两套枚举迟早分叉,而分叉时两边各自都是绿的。

## 它不做什么

- **不写库。** 返回一个「可以插进去的 dict」,由调用方写。
- **不发布。** 冻结 ≠ 发布(规格 §16)—— 发布引用由 `release_manifests` 管。
- **不判这些限制合不合理。** 数值是业务填的(规格 §5.3:那些是建议初值)。
"""
import hashlib
import os
import sys

# 复用缓存那边的规范化器 —— **不另写一套**。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "cache"))
import key_builder as _KB

门店V3 = "store_v3"
后台编排 = "admin_agent_loop"
入口们 = (门店V3, 后台编排)

# 计数口径。**和迁移里的 CHECK 约束同一套字面量**(规格 §5.2)。
旧口径 = "legacy"
新口径 = "v2"
口径们 = (旧口径, 新口径)

# ⚠️ **哈希只覆盖这些** —— 显式清单,不是「整个草稿 dump 一遍」。
# 加字段时要想一句:**它影响执行吗**?不影响就别加进来。
_要算进哈希的 = ("entry_kind", "scope", "limits", "counter_schema_version",
             "support_conditions")

# 哪些限制「必须是正整数」,哪些「允许 0」—— 规格 §5.3 最后一段。
# ⚠️ 这份清单是**白名单**:认不出的键一律拒绝,而不是放过。
# 放过的话,一个拼错的键名(`tool_attemps_cap`)会安静地冻进版本里,
# 而执行层读不到它 —— 于是**那个保护从来没生效过,而页面上填着数**。
_正整数 = ("sdk_turn_cap", "model_request_cap", "tool_request_cap",
         "tool_attempt_cap", "tool_timeout_seconds", "task_deadline_seconds",
         "no_progress_window", "concurrent_tools", "human_wait_seconds")
_允许零 = ("max_retries_per_action", "replan_limit")
_数字键 = _正整数 + _允许零
# 费用上限单独一档:它是金额,可以是小数,而且**必须带币种**(规格 §5.3)。
_金额键 = ("cost_cap_amount",)
_其他键 = ("cost_cap_currency",)
认得的limits键 = _数字键 + _金额键 + _其他键


class 冻不了(Exception):
    """草稿本身讲不通 —— 当场抛,**不冻一个半成品**。

    ⚠️ 冻结是不可变的:一旦冻进去,这一版会被回执核验、被 Run 引用。
    一个形状不对的版本冻进去之后,**错误会沿着整条链路跑下去**,
    而每一环看起来都正常。
    """


def 算内容哈希(草稿):
    """只覆盖 `_要算进哈希的` 那几个字段。

    ⚠️ `support_conditions` 在算之前**排序**:它是「要求支持哪些限制」的集合,
    顺序没有语义。而 `_规范` 故意不排数组(检索结果的顺序会改变答案),
    所以**这件事在这儿做**,不是去改那个规范化器 ——
    改它会影响缓存键,而缓存键那边的保序是对的。
    """
    料 = {}
    for k in _要算进哈希的:
        v = 草稿.get(k)
        if k == "support_conditions":
            v = sorted(v or [], key=str)
        料[k] = v
    return hashlib.sha256(_KB.规范化(料).encode("utf-8")).hexdigest()


def 查形状(草稿):
    """返回问题清单(空 = 没问题)。**不抛** —— 给编辑页用。

    分成一个单独的函数,是为了让页面能**在点「冻结」之前**就把问题
    原位报出来(规格 §9.3:「越界/不支持字段**原位报错**」)。
    """
    问 = []
    if 草稿.get("entry_kind") not in 入口们:
        问.append(f"`entry_kind` 得是 {入口们} 之一,现在是 "
                 f"{草稿.get('entry_kind')!r} —— 规格 §2.2:两条入口不通用,"
                 f"一边的限制在另一边可能根本没有执行点")
    if 草稿.get("counter_schema_version") not in 口径们:
        问.append(f"`counter_schema_version` 得是 {口径们} 之一 —— "
                 f"规格 §5.2:现有计数在网关之前增加、可能含被拒请求,"
                 f"**旧数据要留着 `legacy` 的含义**。"
                 f"而一个用新口径读旧数的统计,和一个口径对上的,"
                 f"在那个数字上长得一模一样")

    lim = 草稿.get("limits")
    if not isinstance(lim, dict) or not lim:
        问.append("`limits` 得是个非空 dict —— **一版空 limits 的策略,"
                 "和一版「不限制」的,在那次运行上长得一模一样**")
        lim = {}

    for k, v in lim.items():
        if k not in 认得的limits键:
            # ⚠️ **认不出就拒绝,不放过。** 一个拼错的键名会安静地冻进版本,
            # 执行层读不到它 —— 那个保护从来没生效过,而页面上填着数。
            问.append(f"`limits.{k}` 这个键不认得 —— **不放过它**:"
                     f"拼错的键会冻进版本而执行层读不到,"
                     f"于是那个保护从来没生效过,**而页面上填着数**。"
                     f"认得的是 {认得的limits键}")
            continue
        if k in _数字键:
            # ⚠️ **bool 要先判** —— 它是 int 的子类,而 `True == 1`。
            # 规格 §5.3:「布尔值不能作为数字」。
            if isinstance(v, bool):
                问.append(f"`limits.{k}` 是布尔 {v!r} —— 规格 §5.3:"
                         f"**布尔值不能作为数字**。"
                         f"`True` 在执行层读出来等于 1,于是"
                         f"**一条上限 1 次的策略,和一条写着 `true` 的,"
                         f"在执行时长得一模一样**,而填的人以为打开了这个保护")
            elif not isinstance(v, int):
                问.append(f"`limits.{k}` 得是整数,现在是 {type(v).__name__}")
            elif k in _正整数 and v <= 0:
                问.append(f"`limits.{k}` 得是**正整数**,现在是 {v} —— "
                         f"0 在这儿不是「不限制」,规格 §5.3 要求次数/秒数为正整数"
                         f"(允许 0 的只有 {_允许零})")
            elif k in _允许零 and v < 0:
                问.append(f"`limits.{k}` 不能是负数,现在是 {v}")
        if k in _金额键:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                问.append(f"`limits.{k}` 得是数字,现在是 {type(v).__name__}")
            elif v <= 0:
                问.append(f"`limits.{k}` 得大于 0,现在是 {v}")
            elif not str(lim.get("cost_cap_currency") or "").strip():
                # 规格 §5.3:「费用上限 → 发布负责人填写**币种和金额**」。
                问.append("填了 `cost_cap_amount` 而没有 `cost_cap_currency` —— "
                         "**一个没有币种的金额不是金额**;规格 §5.3 还要求"
                         "价格口径和版本,**不能把未知价格视为零**")

    # ③ support_conditions 必须指向 limits 里真有的键
    要求 = 草稿.get("support_conditions")
    if 要求 is None or not isinstance(要求, (list, tuple)):
        问.append("`support_conditions` 得是个列表(可以是空的)—— "
                 "**空列表和没给是两件事**:`[]` 是「这一版不要求任何硬限制支持」,"
                 "而没给是「没人想过这件事」")
    else:
        野 = [x for x in 要求 if x not in lim]
        if 野:
            问.append(f"`support_conditions` 里 {野} 在 `limits` 里没有 —— "
                     f"要求实例支持一个**这一版没填的限制**,"
                     f"会让 `策略解析` 永远拒绝启动,"
                     f"而报错指向「实例不支持」而不是「策略写错了」。"
                     f"> 一句解释错了东西的报错,比不解释更误导人")
    return 问


def 冻(*, 草稿, 版本号, 上一版号=None):
    """冻成一版。返回**可以插进 `execution_policy_versions` 的 dict**。

    `版本号` 由调用方给(它要查库);`上一版号` 给了就校验递增。
    """
    问 = 查形状(草稿)
    if 问:
        raise 冻不了("这份草稿冻不了:\n  · " + "\n  · ".join(问))

    if not isinstance(版本号, int) or isinstance(版本号, bool) or 版本号 <= 0:
        raise 冻不了(f"`版本号` 得是正整数,现在是 {版本号!r}")
    if 上一版号 is not None:
        if not isinstance(上一版号, int) or 上一版号 <= 0:
            raise 冻不了(f"`上一版号` 得是正整数或 None,现在是 {上一版号!r}")
        if 版本号 != 上一版号 + 1:
            # ⚠️ **密集递增,不是「只要更大」。** 跳号之后「v3 之后是 v5」,
            # 而一堆地方(页面的「上一版」、差异对比、回滚)隐含依赖
            # 「上一版 = 当前号 - 1」。
            # > 一个跳了号的版本序列,和一个密集的,**在最新那一版上长得一样**。
            raise 冻不了(
                f"版本号要**紧接着**上一版:上一版 {上一版号},"
                f"这一版该是 {上一版号 + 1},给的是 {版本号} —— "
                f"「版本号唯一且密集」是页面「上一版」、差异对比和回滚"
                f"都在隐含依赖的不变量")

    return {
        "application_id": 草稿["application_id"],
        "entry_kind": 草稿["entry_kind"],
        "scope": 草稿.get("scope") or {},
        "limits": 草稿["limits"],
        "counter_schema_version": 草稿["counter_schema_version"],
        # 排好序存 —— 这样库里那一份和算哈希用的那一份是同一个顺序,
        # 不然「哈希对不上」会出现在一个没人想得到的地方。
        "support_conditions": sorted(草稿.get("support_conditions") or [], key=str),
        "version_no": 版本号,
        "content_hash": 算内容哈希(草稿),
    }


def 内容变了吗(草稿, 上一版的哈希):
    """这一版和上一版**内容**变了吗 —— 页面的「要不要出新版本」。

    ⚠️ 用它来挡住「改了一句备注就冒一个新版本」:
    > 一个因为改了备注而冒出来的新版本,和一个真的改了限制的,
    > **在版本列表上长得一模一样**,而回滚的人分不出该回到哪一版。
    """
    现 = 算内容哈希(草稿)
    return (现 != 上一版的哈希), 现
