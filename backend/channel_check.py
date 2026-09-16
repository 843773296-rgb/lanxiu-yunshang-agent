#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多渠道对比的检查 —— **一张不能用来比渠道的表,必须自己说出来。**

这套检查和别的不一样:它钉的不是「数算得对不对」,是「**这个数的来路有没有跟着一起给**」。

因为这里的数**全都算得对**:每个分母都是真的,每个百分比都是照着数据算的。
错的是**归因的对象** —— `source` 这一列不是客户从哪儿下单决定的:

    种子的 46 单    `SRC[i % 4]` —— **按订单序号轮着发的**
    模拟的 3826 单  按固定权重独立抽,和金额、状态、客户**全无关**

实测微信小程序客单价 20866、门店 Pad 4066 —— **差 5 倍,而这个差全是 `i % 4` 的产物**。

> **一张假表和一张真表长得一模一样** —— 都是四行,每行一个百分比。
> 所以不能靠「数对不对」去分辨,只能靠**来路说没说**。

## 还钉一件:共线要**现算**,不许背一句话

`seed.py` 里 `SRC[i % 4]` 和 `ACT[i % 4]` 同周期,于是
**按渠道分组 ≡ 按活动分组**。这条同时影响 `activity_roi` ——
它原来列了三条警告(归因期外、应收实收、取消单),**唯独没有这一条**。

种子数据一改,共线可能就不成立了。所以两处都是**现算**,
背一句话的话,数据改了而警告还在,那就成了另一种假话。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]

咬合 = [
    ("把「这张表不能用来比渠道」那一栏从工具出口去掉",
     "工具出口必须自己说「这张表不能用来比渠道」"),
    ("把共线改成写死 True(不现算)",
     "共线是现算出来的,不是背的"),
    ("把「客服代下单」从「不是渠道」里拿掉,并进四个渠道",
     "客服代下单不许和另外三个并列"),
    ("让 比率() 不再附「一单值多少个百分点」",
     "每个比率都要带着「一单值多少个百分点」"),
    ("让 activity_roi 不再报共线警告",
     "activity_roi 也要带上共线那条警告"),
    ("把 TL31 里「不是渠道的表现」那句删掉",
     "TL31 说清渠道差异不是渠道的表现"),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("多渠道对比 · 检查")
    print("=" * 84)
    import channel as CH, api, prompts

    r = api.channel_compare()

    # ── ① 来路必须跟着数一起给 ────────────────────────────────────────
    ck("工具出口必须自己说「这张表不能用来比渠道」",
       bool(r.get("⚠️ 这张表不能用来比渠道")), len(r),
       "**这里的数全都算得对** —— 错的是归因的对象,"
       "所以分辨不了「数对不对」,只能看**来路说没说**")
    why = str(r.get("⚠️ 这张表不能用来比渠道") or "")
    for 词, 为什么 in (("i % 4", "种子订单按订单序号轮着发"),
                      ("独立", "模拟订单按固定权重独立抽,和别的全无关")):
        ck(f"来路里说到「{词}」", 词 in why, 1, 为什么)

    ck("默认不把模拟订单算进来",
       "只算种子订单" in str(r.get("算的是") or ""), 1,
       "模拟订单的渠道是**抽出来的** —— 算进来只会让表看起来更可信,不会更真")
    r2 = api.channel_compare(include_sim=True)
    ck("算进模拟订单时要说出来",
       "含" in str(r2.get("算的是") or "") and "模拟" in str(r2.get("算的是") or ""), 1,
       "**同一张表两种口径** —— 不说清算的是哪一批,读的人无从分辨")

    # ── ② 共线:现算,不是背 ──────────────────────────────────────────
    共 = r.get("共线现算的结果") or {}
    ck("共线是现算出来的,不是背的",
       "每个渠道绑了哪些活动" in 共 and 共.get("是不是一一对应") is True,
       len(共.get("每个渠道绑了哪些活动") or {}),
       "**种子数据一改共线可能就不成立** —— 背一句话的话,"
       "数据改了而警告还在,那是另一种假话")

    # 自己再独立数一遍,和工具报的对上
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    模拟 = {x["order_id"] for x in c.execute("SELECT order_id FROM sim_batch")}
    对 = {}
    for x in c.execute("SELECT id, source, COALESCE(activity,'(无)') a FROM ordr"):
        if x["id"] in 模拟: continue
        对.setdefault(x["source"], set()).add(x["a"])
    真一对一 = all(len(v) == 1 for v in 对.values()) and \
               len({next(iter(v)) for v in 对.values()}) == len(对)
    ck("工具算的共线和独立数出来的一致",
       共.get("是不是一一对应") == 真一对一, len(对),
       f"四个渠道各绑 {[len(v) for v in 对.values()]} 个活动 —— "
       f"**按渠道分组 ≡ 按活动分组**")

    ck("activity_roi 也要带上共线那条警告",
       bool(api._活动渠道共线()), 1,
       "它原来列了三条警告(归因期外、应收实收、取消单),**唯独没有这一条** —— "
       "而这条最难发现:**它不在任何一个数上**")

    # ── ③ 客服代下单不许并列 ──────────────────────────────────────────
    ck("客服代下单不许和另外三个并列",
       "客服代下单" in (r.get("不算渠道的") or {})
       and "客服代下单" not in (r.get("四个渠道") or {}), 1,
       "它是**人工补录** —— 「客服代下单客单价最高」可能只是「大单更需要人工跟」")
    ck("而且要说清它为什么不是渠道",
       "⚠️ 这不是一个渠道" in ((r.get("不算渠道的") or {}).get("客服代下单") or {}), 1)

    # ── ④ 每个比率都要带着「一单值多少」───────────────────────────────
    比率们 = [v for d in (r.get("四个渠道") or {}).values()
              for k, v in d.items() if "/" in str(v)]
    ck("每个比率都要带着「一单值多少个百分点」",
       比率们 and all("一单就值" in str(x) for x in 比率们), len(比率们),
       "**「1/11」和「9%」是两种说法** —— 后者看起来精确得多,"
       "而一单进出就是 9 个百分点")
    ck("分母为零不给数", CH.比率(0, 0)[1] is None, 1,
       "**没有分母的「没问题」不是信息** —— 和 review.rate 同一条,不写第二遍")
    # **不许编「样本至少多少」的门槛** —— 那是业务判断
    src = open(os.path.join(ROOT, "knowledge", "channel.py"), encoding="utf-8").read()
    代码 = "\n".join(l.split("#")[0] for l in src.splitlines())
    import re as _re
    代码 = _re.sub(r'"""[\s\S]*?"""', "", 代码)
    门槛 = _re.findall(r'分母\s*[<>]=?\s*(\d+)', 代码)
    ck("口径里不许编「样本至少多少」的门槛", not 门槛, len(代码.splitlines()),
       f"找到 {门槛}" if 门槛 else
       "**多小算小是业务判断** —— 改成把「一单值多少个百分点」摆出来")

    ck("不给渠道排名", "不给渠道排名" in r, 1,
       "**11 单的样本排不出名次,排了会被当成结论去调预算**")

    # ── ⑤ 规矩和工具在同一个角色身上 ──────────────────────────────────
    tl31 = [x for x in prompts.TASK_RULES if x.id == "TL31"]
    ck("TL31 和 channel_compare 在同一个角色身上",
       bool(tl31) and "channel_compare" in (tl31[0].needs if tl31 else ()),
       len(prompts.TASK_RULES),
       "**「工具给了,规矩没给」比「工具没给」更危险**")
    文 = tl31[0].text if tl31 else ""
    ck("TL31 说清渠道差异不是渠道的表现",
       "不是渠道的表现" in 文, 1)
    for 词, 为什么 in (("一单就值", "每个比率都要带着一单值多少个百分点"),
                      ("人工补录", "客服代下单不是渠道"),
                      ("不排名", "排了会被当成结论去调预算")):
        ck(f"TL31 里说到「{词}」", 词 in 文, 1, 为什么)

    d = [x for x in api.SHOP_SCHEMAS if x["name"] == "channel_compare"][0]["description"]
    for 词 in ("不能用来比渠道", "共线", "人工补录"):
        ck(f"工具描述里说到「{词}」", 词 in d, 1)

    print()
    if FAIL:
        print(f"\033[31m❌ 多渠道对比 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 多渠道对比全部符合预期\033[0m")
    print(f"    四个渠道的数全都算得对,而**这张表不能用来比渠道** —— "
          f"来路跟着数一起给了,共线是现算的。")


if __name__ == "__main__":
    main()
