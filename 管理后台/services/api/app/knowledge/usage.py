#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次模型调用折成**用量账目**(纯逻辑,零 IO)。

## 记录仪和账本是两件事(见 `llmtrace.py` 文件头)

    记录仪   「发生了什么」—— 模型、耗时、成功没成功。写 JSONL
    账本     「算多少钱」  —— 写库,有幂等键防重复计费

这个文件只管后者的**算法那一半**:给定一次调用的用量和一份价目表,
算出该往 `usage_ledger` 写几行、每行多少。写库在调用方。

## ⚠️ 没有价目表时:**token 记成已知,金额记成未知**

库里现在 `pricing_versions` **一条都没有** —— 没有任何一份
Claude / DeepSeek 的价目表快照。

这时候有三种做法,只有一种是对的:

  ① 编一个单价        → 界面上出现一个**自信的、错的金额**。最糟
  ② 什么都不记        → token 用量也一起丢了,而那是事后最难重建的
  ③ **token 已知、金额未知** ← 这个

② 之所以也不行:用量是**当时才有**的事实(响应里的 usage),
过了就没了;而价格是**随时可以补**的(补一份快照,历史用量重算即可)。
把两者绑在一起丢,是拿可补的东西去牺牲不可补的东西。

契约里早就给③留了位置:`amount_known=False` 时前端显示「未知」,
**不许显示 0**。0 和未知在报表上差别巨大 ——
0 意味着「跑了但不花钱」,未知意味着「花了多少还不知道」。

## ⚠️ 不信 SDK 自己报的总价

并行会话实测:Agent SDK 返回的 `total_cost_usd` 跨供应商时**差过 24 倍、135 倍**
(CLI 拿 Claude 的价目表去算 DeepSeek 的 token)。
所以这里**只收 token 数**,价格一律从 `pricing_versions` 查 ——
供应商不同,单价就不同,而一个跨供应商算错的金额不会报错。
"""

# 资源类型。**和 `usage_ledger.resource` 对齐**,不另立一套。
精排 = "rerank"
向量化 = "embed"
生成 = "generate"

# ⚠️ **token 分档收**,不合成一个数:
# 输入 / 输出 / 缓存读 / 缓存写 的单价差一个数量级以上,
# 合成一个总数之后,**补上价目表也算不回来了** —— 分档是当时才有的事实。
token档 = ("input_tokens", "output_tokens",
           "cache_creation_input_tokens", "cache_read_input_tokens")


class 用量不对(Exception):
    """用量本身有问题 —— **当场抛,不写一条半真的账**。"""


def 归一用量(用量):
    """把供应商返回的 usage 折成 `{档: 数}`。**认不出的档要报出来,不吞掉。**

    吞掉的后果:供应商加了一档新计费(比如某种新缓存),
    它的 token **一分钱都不会被算进来**,而总额看起来完全正常。
    """
    用量 = dict(用量 or {})
    # ⚠️ **值为 0 的档不算一档。** Claude 每次都返回
    # `cache_creation_input_tokens: 0` / `cache_read_input_tokens: 0`(没用缓存),
    # 而第一版把每个**出现过**的档都写一行 —— 于是账本里多出一堆 quantity=0 的账。
    #
    # 这个文件自己写着「**不写一条 quantity=0 的账**:0 意味着「跑了但没花」」,
    # 而那条规矩当时只拦住「整次调用一个档都没有」,没拦住「某一档是 0」。
    # > **规矩只在它想到的那一层生效。**
    #
    # 0 的档不该占一行:它给报表添噪音,而且一条 `quantity=0, amount=null`
    # 的账读起来像「花了未知的钱」,实际是「这一档没用上」。
    出 = {k: int(用量.pop(k)) for k in token档
         if 用量.get(k) is not None and int(用量[k]) != 0}
    # 把 0 的那些也从剩余里摘掉 —— 它们是**认得出的档**,只是这次是 0,
    # 报进「认不出的档」会是假警报。
    for k in token档:
        用量.pop(k, None)
    # ⚠️ **剩下的一律报出来,不管是不是数字。**
    # 第一版只收 `isinstance(v, (int, float))` 的,于是 Claude 返回里那层嵌套的
    # `cache_creation: {ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}`
    # **静静地被漏掉了** —— 它是个 dict,不是数字,所以连「认不出」都没报。
    #
    # 而那正是这个函数存在的理由:供应商加一档新计费时,
    # 它的 token 一分钱都不会被算进来,**而总额看起来完全正常**。
    # 判据要是只认它想得到的形状,就只能发现它想得到的问题。
    剩 = sorted(用量)
    return 出, 剩


def 折成账目(*, 用量, 模型, 提供方, 资源=精排, 价目=None, 事件键, trace_id=None,
          是mock=False, 调用方=None, 世界日期=None):
    """一次调用 → 要写进 `usage_ledger` 的那几行(不写库)。

    `价目` 是 `pricing_versions` 里那一份的 `unit_prices`(dict),**给 None 就是没有**。
    返回 dict(行们, 认不出的档, 金额已知吗, 为什么不知道)。

    ⚠️ **每一档一行**,不是一次调用一行。理由:
    档的单价不同,合成一行之后 `quantity` 就没有单位可言了 ——
    「3000 个 token」在输入和输出上是两个价钱。
    """
    if not 事件键:
        raise 用量不对("没给事件键 —— **它是防重复计费的唯一凭据**,不许自动生成")
    档们, 认不出 = 归一用量(用量)
    if not 档们:
        raise 用量不对(
            f"这次调用一个认得出的 token 档都没有(拿到 {sorted((用量 or {}))}) —— "
            f"**不写一条 quantity=0 的账**:0 意味着「跑了但没花」,"
            f"而这里的真相是「不知道花了多少」")

    行们, 金额已知 = [], 价目 is not None
    for 档, n in sorted(档们.items()):
        单价 = (价目 or {}).get(档)
        有价 = 单价 is not None
        if not 有价:
            金额已知 = False
        行们.append(dict(
            event_key=f"{事件键}:{档}",      # ⚠️ 带档名:一次调用几行,键不能撞
            trace_id=trace_id, resource=资源, quantity=n, unit="token",
            currency=(价目 or {}).get("currency", "USD"),
            # ⚠️ **算不出就写 None,不写 0**(契约:unknown 区分 zero)
            amount=(round(n * 单价, 6) if 有价 else None),
            amount_known=bool(有价),
            # ⚠️ **`source` 是执行模式,不是供应商。** 这两件事混在一列里过
            # (2026-09-28 migration 60c49c3174eb 修的),而混了不报错:
            # 「mock」和「anthropic」并排在同一列里,看起来像两个供应商。
            source=("mock" if 是mock else "live"),
            # mock **没有供应商** —— 留 None 不填 "mock":填了之后它会在
            # 「按供应商」的报表里冒充一个供应商,而它一分钱都没花。
            provider=(None if 是mock else (提供方 or None)),
            caller=调用方, world_date=世界日期,
            档=档, 模型=模型))

    为什么 = None
    if not 金额已知:
        缺 = [r["档"] for r in 行们 if not r["amount_known"]]
        为什么 = (f"没有 {提供方}/{模型} 的价目表快照"
                if 价目 is None else f"价目表里缺这几档的单价:{缺}")
        为什么 += " —— **token 数是已知的,补一份价目表就能重算**"
    return dict(行们=行们, 认不出的档=认不出, 金额已知吗=金额已知, 为什么不知道=为什么)



# ── 写库:**只有这一处** ──────────────────────────────────────────────
# 2026-09-28 抽出来的。在这之前只有检索那条路在写账本,而 A1 上报接口
# 马上就是第二个写入方 —— **两个写入方迟早分叉**,而分叉的表现是
# 两批账用了不同的 `source` 含义(这个错刚刚真发生过一次)。
#
# ⚠️ 这个函数**要连接不开连接**:事务边界是调用方的事
# (调用方可能要把账和别的写入放进同一个事务)。
def 写进库(c, *, 组织, 项目, 谁, 用量, 模型, 提供方, 资源, 事件键, trace_id,
        是mock=False, 调用方=None, 世界日期=None, 价目=None, _新id=None):
    """把一次调用折成账目并写进 `usage_ledger`。返回一段能显示的说明。

    `c` 是**已经在事务里**的连接。`_新id` 是造 id 的函数(调用方给)。
    """
    from sqlalchemy import text as _t
    折 = 折成账目(用量=用量, 模型=模型, 提供方=提供方, 资源=资源, 价目=价目,
                事件键=事件键, trace_id=trace_id, 是mock=是mock,
                调用方=调用方, 世界日期=世界日期)
    写了 = 0
    for 行 in 折["行们"]:
        写了 += c.execute(_t("""
            insert into usage_ledger (id, organization_id, project_id, event_key,
                trace_id, resource, quantity, unit, currency, amount, amount_known,
                source, provider, caller, world_date, created_at, created_by)
            values (:i,:o,:p,:ek,:t,:res,:q,:u,:cur,:amt,:ak,:src,:prov,:call,:wd,
                    now(), :by)
            -- ⚠️ 冲突目标是 **(project_id, event_key)**,精确匹配那条唯一约束。
            -- `do nothing` 是防重复计费的那一半:同一个事件重复上报不加钱。
            on conflict (project_id, event_key) do nothing"""),
            {"i": _新id("ul"), "o": 组织, "p": 项目, "ek": 行["event_key"],
             "t": 行["trace_id"], "res": 行["resource"], "q": 行["quantity"],
             "u": 行["unit"], "cur": 行["currency"], "amt": 行["amount"],
             "ak": 行["amount_known"], "src": 行["source"], "prov": 行["provider"],
             "call": 行["caller"], "wd": 行["world_date"], "by": 谁}).rowcount
    出 = {"写了几行": 写了, "本该几行": len(折["行们"]),
         "金额已知吗": 折["金额已知吗"],
         "token合计": sum(r["quantity"] for r in 折["行们"])}
    if 写了 < len(折["行们"]):
        # ⚠️ **重复上报要报出来,不当成成功。** 它多半是对的(网络重发),
        # 但「重发了」和「第一次就写进去了」是两件事 ——
        # 上报方需要知道自己发了两遍,否则它会以为自己只发过一次。
        出["重复的行数"] = len(折["行们"]) - 写了
        出["说明"] = ("这个事件键之前已经记过账了 —— **没有重复计费**。"
                   "如果你以为这是第一次上报,那说明上一次其实成功了")
    if 折["为什么不知道"]:
        出["为什么金额未知"] = 折["为什么不知道"]
    if 折["认不出的档"]:
        出["认不出的用量档"] = 折["认不出的档"]
    return 出
