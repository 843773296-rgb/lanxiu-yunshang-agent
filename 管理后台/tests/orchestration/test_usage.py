#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用量折账的纯逻辑 —— **零 IO,跑在 CI 里**。

## 这一组要守住的三件

    ① **没有价目表时:token 已知、金额未知** —— 不编单价,也不写 0
    ② **token 分档记**,不合成一个数(档的单价差一个数量级以上)
    ③ **认不出的档要报出来** —— 供应商加一档新计费时,
      它的 token 一分钱都不会被算进来,**而总额看起来完全正常**

第 ③ 条第一版写错过:只收 `isinstance(v, (int, float))` 的,
于是 Claude 返回里那层嵌套的 `cache_creation: {...}` **连「认不出」都没报**。
> **判据只认它想得到的形状时,就只能发现它想得到的问题。**
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "knowledge"))

import usage as U

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


# Claude 真实返回的形状(2026-09-28 实测抄回来的)
真用量 = {"input_tokens": 4974, "output_tokens": 636,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation": {"ephemeral_5m_input_tokens": 0,
                           "ephemeral_1h_input_tokens": 0},
        "service_tier": "standard", "inference_geo": "global"}

print("▸ ① 没有价目表:token 已知,金额未知,**不是 0**")
r = U.折成账目(用量=真用量, 模型="claude-haiku-4-5", 提供方="anthropic",
           事件键="tr_x:rerank", trace_id="tr_x")
ck("金额已知 = False", r["金额已知吗"] is False)
ck("**每一行的 amount 是 None,不是 0**(0 意味着「跑了但没花」)",
   all(x["amount"] is None for x in r["行们"]), [x["amount"] for x in r["行们"]])
ck("而 quantity 是真数(用量是当时才有的事实,过了就没了)",
   sum(x["quantity"] for x in r["行们"]) == 4974 + 636,
   sum(x["quantity"] for x in r["行们"]))
ck("amount_known 每行都是 False", all(x["amount_known"] is False for x in r["行们"]))
ck("说清为什么不知道,而且点明「补一份价目表就能重算」",
   "价目表" in (r["为什么不知道"] or "") and "重算" in (r["为什么不知道"] or ""),
   r["为什么不知道"])

print("▸ ② token 分档:一次调用写几行,不合成一个数")
# ⚠️ **真用量里那两档缓存正好是 0**(这次没用缓存),而 0 的档不占行(见 ②b)。
# 所以测「多档」要用一份**四档都非零**的用量,否则这条断言测的是别的东西。
用了缓存的 = {"input_tokens": 100, "output_tokens": 20,
          "cache_creation_input_tokens": 7, "cache_read_input_tokens": 3}
r多 = U.折成账目(用量=用了缓存的, 模型="m", 提供方="anthropic", 事件键="tr_y:rerank")
ck("四档都非零 → 4 行", len(r多["行们"]) == 4, [x["档"] for x in r多["行们"]])
ck("event_key 带档名(一次调用几行,键不能撞)",
   len({x["event_key"] for x in r多["行们"]}) == 4,
   [x["event_key"] for x in r多["行们"]])
ck("每行的 event_key 都以事件键开头",
   all(x["event_key"].startswith("tr_y:rerank:") for x in r多["行们"]))
ck("**不合成一个数**:因为档的单价差一个数量级,合了就补不回来",
   len({x["档"] for x in r多["行们"]}) == 4)

print("▸ ②b **值为 0 的档不占一行** —— 这个文件自己的规矩,补到了这一层")
# 第一版把每个**出现过**的档都写一行,于是 Claude 每次返回的两个 0 缓存档
# 各占一行 —— 账本里多出一堆 `quantity=0, amount=null` 的账,
# 读起来像「花了未知的钱」,实际是「这一档没用上」。
# > **规矩只在它想到的那一层生效。**
ck("真用量(两档缓存是 0)→ 只有 2 行", len(r["行们"]) == 2,
   [(x["档"], x["quantity"]) for x in r["行们"]])
ck("没有任何一行 quantity 是 0", all(x["quantity"] != 0 for x in r["行们"]))
ck("**0 的档不会被报成「认不出」**(它是认得出的档,只是这次是 0)",
   not ({"cache_creation_input_tokens", "cache_read_input_tokens"}
        & set(r["认不出的档"])), r["认不出的档"])

print("▸ ③ 认不出的档要报出来 —— 不管它是什么形状")
# ⚠️⚠️ **这一条 2026-10-04 翻过面,而且是往「更强」那边翻的。**
#
# 原来断的是「嵌套 dict 的 `cache_creation` **被报出来**」——
# 那时它是个**认不出的**字段,而这个文件的保护就是「认不出的要报」。
#
# 现在它**认得出了**:`归一用量` 会按它把缓存写入拆成
# 5 分钟 / 1 小时两档并**分别计价**(两档单价差 60%)。
# 所以它不该再出现在「认不出」名单里 —— 那不是保护被削弱,是保护被升级:
# 从「这个字段我不懂,报给你」变成「这个字段我懂,而且算对了钱」。
#
# ⚠️ **而「认不出的要报」这条规矩本身没放松** —— 它现在守的是更里面一层:
# 嵌套里出现一个**没见过的 TTL 键**(比如哪天有了 24 小时档)时仍然要报,
# 那一条在第 ⑩ 组里验。
ck("`cache_creation` **不再进「认不出」名单** —— 它现在是认得出、"
   "而且按 TTL 分档计价的(保护升级,不是放松)",
   "cache_creation" not in r["认不出的档"], r["认不出的档"])
ck("字符串的 `service_tier` / `inference_geo` 也报",
   {"service_tier", "inference_geo"} <= set(r["认不出的档"]), r["认不出的档"])
ck("认得出的那四档**不在**认不出清单里(证明不是把所有键都报了)",
   not (set(U.token档) & set(r["认不出的档"])), r["认不出的档"])
# 咬合:假装供应商加了一档新的数字型计费
r2 = U.折成账目(用量={**真用量, "新档_input_tokens": 999}, 模型="m", 提供方="p",
            事件键="k")
ck("加一档没见过的数字计费 → 报出来,**而且它的 token 没被算进总数**",
   "新档_input_tokens" in r2["认不出的档"]
   and sum(x["quantity"] for x in r2["行们"]) == 4974 + 636,
   sum(x["quantity"] for x in r2["行们"]))

print("▸ ④ 有价目表就真算")
价 = {"input_tokens": 0.000001, "output_tokens": 0.000005, "currency": "USD"}
r3 = U.折成账目(用量={"input_tokens": 1000, "output_tokens": 200}, 模型="m",
             提供方="anthropic", 事件键="k2", 价目=价)
ck("金额已知 = True", r3["金额已知吗"] is True)
ck("算出来的钱对得上", sorted(x["amount"] for x in r3["行们"]) == [0.001, 0.001],
   [x["amount"] for x in r3["行们"]])
ck("币种跟着价目表走", all(x["currency"] == "USD" for x in r3["行们"]))
r4 = U.折成账目(用量={"input_tokens": 1000, "output_tokens": 200}, 模型="m",
             提供方="anthropic", 事件键="k3",
             价目={"input_tokens": 0.000001, "currency": "USD"})
ck("**价目表缺一档 → 整体判成金额未知**(缺的那行 amount 是 None)",
   r4["金额已知吗"] is False
   and [x["amount"] for x in sorted(r4["行们"], key=lambda z: z["档"])] == [0.001, None],
   [(x["档"], x["amount"]) for x in r4["行们"]])
ck("而且说清缺的是哪几档", "output_tokens" in (r4["为什么不知道"] or ""),
   r4["为什么不知道"])

print("▸ ⑤ 拒绝写一条半真的账")
for 坏用量, 说 in (({}, "空用量"), ({"service_tier": "standard"}, "一个 token 档都没有"),
              (None, "None")):
    try:
        U.折成账目(用量=坏用量, 模型="m", 提供方="p", 事件键="k")
        ck(f"{说} → 抛", False, "没抛!会写出一条 quantity=0 的账")
    except U.用量不对 as e:
        ck(f"{说} → 当场抛", True, str(e)[:70])
try:
    U.折成账目(用量=真用量, 模型="m", 提供方="p", 事件键="")
    ck("没给事件键 → 抛", False, "没抛!事件键是防重复计费的唯一凭据")
except U.用量不对:
    ck("没给事件键 → 抛(**它是防重复计费的唯一凭据,不许自动生成**)", True)

print("▸ ⑥ `source` 是执行模式,`provider` 才是供应商 —— **这两件事混在一列里过**")
# 2026-09-28:`source` 当时有两个含义(Worker 写 execution_mode、精排写提供方),
# 两种值都是合法字符串,分组查询照样出结果,**只是看起来像两个供应商**。
# migration 60c49c3174eb 把它们分开了。这一组守着别再混回去。
r5 = U.折成账目(用量=真用量, 模型="emb-mock", 提供方="anthropic", 事件键="k4", 是mock=True)
ck("是mock → source='mock'", all(x["source"] == "mock" for x in r5["行们"]))
ck("**而 provider 是 None,不是 'mock'** —— 填了它会在「按供应商」的报表里"
   "冒充一个供应商,而它一分钱都没花",
   all(x["provider"] is None for x in r5["行们"]),
   [x["provider"] for x in r5["行们"]])
r6 = U.折成账目(用量=真用量, 模型="m", 提供方="anthropic", 事件键="k5")
ck("不是 mock → source='live'(执行模式)", all(x["source"] == "live" for x in r6["行们"]))
ck("而 provider='anthropic'(供应商)", all(x["provider"] == "anthropic" for x in r6["行们"]))
ck("**两列的值不许相等** —— 相等就说明又混回去了",
   all(x["source"] != x["provider"] for x in r6["行们"]))

print("▸ ⑧ 调用方和世界日期 —— 并行会话要的那两个")
r7 = U.折成账目(用量=真用量, 模型="m", 提供方="deepseek", 事件键="k6",
             调用方="门店助手:值班研判", 世界日期="2026-09-28")
ck("caller 传下去了(**没有它只答得出「一共花了多少」**)",
   all(x["caller"] == "门店助手:值班研判" for x in r7["行们"]))
ck("world_date 传下去了(演示世界的钟和真实时钟是两个)",
   all(x["world_date"] == "2026-09-28" for x in r7["行们"]))
ck("不给就是 None,**不拿今天顶上** —— 猜一个日期比没有日期糟",
   all(x["caller"] is None and x["world_date"] is None for x in r6["行们"]))

print("▸ ⑦ 资源类型和契约对齐,不另立一套")
ck("默认资源是 rerank", r["行们"][0]["resource"] == U.精排 == "rerank")
ck("三种资源都是 ASCII(它们进 `usage_ledger.resource` 列)",
   all(x.isascii() for x in (U.精排, U.向量化, U.生成)),
   [U.精排, U.向量化, U.生成])

print("▸ ⑨ 参考价:**按标价估的,不是账单**(2026-09-28 查的真价)")
# 价从这两处查的:
#   Claude    https://platform.claude.com/docs/en/about-claude/pricing
#   DeepSeek  https://api-docs.deepseek.com/quick_start/pricing
海ku = {"input_tokens": 1.0 / 1_000_000, "output_tokens": 5.0 / 1_000_000,
       "cache_read_input_tokens": 0.10 / 1_000_000, "currency": "USD"}
r9 = U.折成账目(用量={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
             模型="claude-haiku-4-5", 提供方="anthropic", 事件键="k9", 价目=海ku)
金 = {x["档"]: x["amount"] for x in r9["行们"]}
ck("一百万 input → $1.00", 金["input_tokens"] == 1.0, 金)
ck("一百万 output → $5.00", 金["output_tokens"] == 5.0, 金)
ck("**单位是「每 token 多少钱」不是「每百万」** —— "
   "存成每百万的话折账要多一次除法,而那次除法迟早有人漏掉",
   海ku["input_tokens"] < 0.001)

深 = {"input_tokens": 1.32 / 1_000_000, "output_tokens": 3.96 / 1_000_000,
     "currency": "USD"}
r10 = U.折成账目(用量={"input_tokens": 1_000_000}, 模型="deepseek-v4-pro",
              提供方="deepseek", 事件键="k10", 价目=深)
ck("DeepSeek 取**高峰价**($1.32,非高峰是一半)—— "
   "取便宜那边会让人低估成本,而低估的代价比高估大",
   r10["行们"][0]["amount"] == 1.32, r10["行们"][0]["amount"])
ck("**两家的单价不一样,所以必须按供应商查表** —— "
   "跨供应商用错价目表实测差过 24 倍、135 倍,而它不报错",
   海ku["input_tokens"] != 深["input_tokens"])

print("▸ ⑩ 缓存写入**按 TTL 分档** —— 两档单价差 60%(2026-10-04 加)")
# ⚠️ `cache_creation_input_tokens` 是**两档的合计**。一手:
# `shared/prompt-caching.md` —— 「Cache writes cost
# **1.25× for 5-minute TTL, 2× for 1-hour TTL**」。
# 原来只认那个合计、只配一个 1.25 的单价,于是 1 小时档的 token
# **按 1.25 计价,少算 37.5%** —— 而这个文件的「认不出的档要报出来」
# 那道闸**拦不住它**:嵌套字段确实被报了,可钱早就按合计算完了。
# > 一道装在错位置的闸,和一道没装的闸,在它响的时候长得一样。
两档价 = {"input_tokens": 1.0 / 1_000_000, "output_tokens": 5.0 / 1_000_000,
        "ephemeral_5m_input_tokens": 1.25 / 1_000_000,
        "ephemeral_1h_input_tokens": 2.00 / 1_000_000,
        "cache_creation_input_tokens": 1.25 / 1_000_000,
        "cache_read_input_tokens": 0.10 / 1_000_000, "currency": "USD"}

档们, 剩 = U.归一用量(dict(真用量, cache_creation_input_tokens=3000,
                      cache_creation={"ephemeral_5m_input_tokens": 1000,
                                      "ephemeral_1h_input_tokens": 2000}))
ck("两档都有 → **拆成两行**,合计那一档不再出现(否则双算)",
   档们.get("ephemeral_5m_input_tokens") == 1000
   and 档们.get("ephemeral_1h_input_tokens") == 2000
   and "cache_creation_input_tokens" not in 档们, 档们)

r11 = U.折成账目(用量=dict(真用量, cache_creation_input_tokens=10000,
                      cache_creation={"ephemeral_5m_input_tokens": 0,
                                      "ephemeral_1h_input_tokens": 10000}),
              模型="claude-haiku-4-5", 提供方="anthropic",
              事件键="k11", 价目=两档价)
金11 = {x["档"]: x["amount"] for x in r11["行们"]}
ck("一万 token 全走 **1 小时**档 → $0.02(2.00/MTok)",
   金11.get("ephemeral_1h_input_tokens") == 0.02, 金11)
ck("**按旧口径会算成 $0.0125 —— 少算 $0.0075**(那一档上少 37.5%)",
   round(0.02 - 10000 * 1.25 / 1_000_000, 6) == 0.0075)

r12 = U.折成账目(用量=dict(真用量, cache_creation_input_tokens=10000,
                      cache_creation={"ephemeral_5m_input_tokens": 10000,
                                      "ephemeral_1h_input_tokens": 0}),
              模型="claude-haiku-4-5", 提供方="anthropic",
              事件键="k12", 价目=两档价)
金12 = {x["档"]: x["amount"] for x in r12["行们"]}
ck("全走 **5 分钟**档 → $0.0125,**和旧口径一样**"
   "(所以这次改动不会让已有的账变样)",
   金12.get("ephemeral_5m_input_tokens") == 0.0125, 金12)
ck("而且 0 的那一档**不占一行**(这个文件的老规矩)",
   "ephemeral_1h_input_tokens" not in 金12, sorted(金12))

# ⚠️ 下面两条是「它不许自己挑一个」的咬合
档坏, _ = U.归一用量(dict(真用量, cache_creation_input_tokens=3000,
                     cache_creation={"ephemeral_5m_input_tokens": 1000,
                                     "ephemeral_1h_input_tokens": 500}))
ck("**分档之和 ≠ 合计 → 当场报出来,不挑一个用** —— "
   "挑合计会漏掉新档的单价,挑分档会少算那部分 token",
   "⚠️缓存写入分档对不上" in 档坏, sorted(档坏))
ck("而且报的时候两个数都在(事后查得出差多少)",
   (档坏.get("⚠️缓存写入分档对不上") or {}).get("合计") == 3000
   and (档坏["⚠️缓存写入分档对不上"]).get("分档之和") == 1500,
   档坏.get("⚠️缓存写入分档对不上"))

档新, _ = U.归一用量(dict(真用量, cache_creation_input_tokens=1000,
                     cache_creation={"ephemeral_5m_input_tokens": 1000,
                                     "ephemeral_1h_input_tokens": 0,
                                     "ephemeral_24h_input_tokens": 0}))
ck("供应商**加了一档没见过的 TTL** → 也要报(哪怕它这次是 0)—— "
   "等它非 0 的那天再发现就已经算错了",
   "⚠️缓存写入分档对不上" in 档新
   and "ephemeral_24h_input_tokens" in str(档新["⚠️缓存写入分档对不上"]),
   档新.get("⚠️缓存写入分档对不上"))

档常, 剩常 = U.归一用量(真用量)
ck("**真实常见形状(两档都是 0)不多报任何东西** —— "
   "6093 条记录里 1 小时档写入是 0 条,这条闸不许在那上面天天响",
   "⚠️缓存写入分档对不上" not in 档常
   # ⚠️ 不能断 `剩常 == []`:`service_tier` / `inference_geo` 本来就是
   # 认不出的**非 token** 字段,每次都在(第一版我断成空,当场红)。
   # 要断的是**这次改动有没有多报东西**,也就是 `cache_creation` 走掉了。
   and "cache_creation" not in 剩常,
   (sorted(档常), 剩常))

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
