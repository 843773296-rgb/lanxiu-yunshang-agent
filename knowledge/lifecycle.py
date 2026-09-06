#!/usr/bin/env python3
"""会员生命周期判定 —— **口径的唯一源头**。

规则逐字来自后台 PRD 6.1(八档 + 判定条件 + 优先级 + 人工调整窗)。

## 为什么单独一个模块

原来这套口径有**两份手抄件**:
  · `backend/seed.py` 的 PRIORITY + match_rules() —— 真正在算的那份
  · `backend/server.py` 的 PRI + RULE —— 页面展示用的那份
两份都写着同一个优先级列表。**同一个事实两个来源,必然漂**,
而且漂了不会报错 —— 页面上写「优先级 3」,实际按第 4 位算,没有任何迹象。

## 为什么不接受「让模型现算」

这套口径全是**含端边界**:第 90 天算活跃、第 91 天进休眠、第 180 天仍是休眠、
第 181 天进潜在流失、第 365 天仍是潜在流失、第 366 天才算流失;
实付满 15000 **含端**计高价值,14999 不算。

模型现写 SQL,`>= 90` 写成 `> 90` 的概率不低,而**错出来的答案看起来完全合理** ——
一个客户被判成休眠,没有任何迹象表明哪里不对。这类错这个项目最怕。
所以口径写在这里,有函数签名、有自测、有真值对账(`backend/member_check.py`)。

## 这个模块不管「今天几号」

判定只吃**已经算好的天数**(idle_days / days_since_first_order / days_since_manual),
不自己取当前日期。理由和工具层「已逾期由工具算好、不让模型拿今天去比」一样:
**谁负责判定,谁就不该同时负责取时间** —— 否则同一批数据在不同时刻算出不同结果,
真值对账就没法复现。取时间是调用方的事。
"""

# 优先级:数字小的压过数字大的。多条件同时命中时取排在前面的那个。
# 真值里三条专门测这个:潜在流失(2) > 高价值(5);流失(1) > 忠诚(4);高价值(5) > 新客(6)。
PRIORITY = ["流失", "潜在流失", "休眠", "忠诚", "高价值", "新客", "活跃", "潜在"]

# 判定条件的**人话版**。页面和工具描述都用这一份,不各写各的。
RULES = {
    "潜在":     "无完成订单",
    "新客":     "首单后 30 天内",
    "活跃":     "90 天内有有效互动",
    "高价值":   "近 12 个月实付满 15000 元",
    "忠诚":     "近 12 个月满 4 单且跨两个季度",
    "休眠":     "无互动 91–180 天",
    "潜在流失": "无互动 181–365 天",
    "流失":     "无互动超过 365 天",
}

# 人工调整的优先期。人调过之后 30 天内以人为准,超过就回到系统重算值。
MANUAL_WINDOW_DAYS = 30


def match(c):
    """返回**命中的全部**条件,不做取舍。

    c 需要:order_cnt / idle_days / amount_12m / orders_12m / quarters_12m,
    以及可选的 days_since_first_order(没有首单就给 None)。

    **每一处边界都是含端的**,写法一律用 <= / >=,不要改成 < / > ——
    真值里六条边界用例(90/91/180/181/365/366)就是钉这个的。
    """
    m = []
    if c.get("order_cnt", 0) == 0: m.append("潜在")
    d1 = c.get("days_since_first_order")
    if d1 is not None and d1 <= 30: m.append("新客")
    idle = c.get("idle_days", 0)
    if idle <= 90: m.append("活跃")
    if c.get("amount_12m", 0) >= 15000: m.append("高价值")
    # 忠诚要**两个条件同时满足** —— 只满 4 单但都在同一季度不算(真值 E-A3-09)
    if c.get("orders_12m", 0) >= 4 and c.get("quarters_12m", 0) >= 2: m.append("忠诚")
    if 91 <= idle <= 180: m.append("休眠")
    if 181 <= idle <= 365: m.append("潜在流失")
    if idle > 365: m.append("流失")
    return m


def decide(c):
    """判定单一主状态。返回判定结果 + **为什么** —— 后者才是给人看的。

    额外可选字段:manual_lc(人工调整成什么)+ days_since_manual(调了多少天)。
    """
    m = match(c)
    sys_lc = next((p for p in PRIORITY if p in m), "潜在")
    manual, dsm = c.get("manual_lc"), c.get("days_since_manual")
    in_window = bool(manual and dsm is not None and dsm <= MANUAL_WINDOW_DAYS)
    final = manual if in_window else sys_lc
    why = []
    if len(m) > 1:
        why.append(f"同时命中 {len(m)} 条({' / '.join(m)}),"
                   f"按优先级取「{sys_lc}」(第 {PRIORITY.index(sys_lc)+1} 位)")
    elif m:
        why.append(f"只命中「{sys_lc}」:{RULES[sys_lc]}")
    else:
        why.append("一条都没命中,落到「潜在」")
    if manual:
        why.append(f"人工调整为「{manual}」{dsm} 天前 —— "
                   + (f"在 {MANUAL_WINDOW_DAYS} 天优先期内,**以人工为准**,系统重算值「{sys_lc}」被抑制"
                      if in_window else
                      f"已超过 {MANUAL_WINDOW_DAYS} 天优先期,**回到系统重算值「{sys_lc}」**"))
    return {"生命周期": final, "系统重算值": sys_lc, "命中": m,
            "优先级": PRIORITY.index(final) + 1 if final in PRIORITY else None,
            "判定条件": RULES.get(final), "人工覆盖生效": in_window, "依据": "；".join(why)}


if __name__ == "__main__":
    # 自测:六个时间含端点 + 金额含端 + 忠诚跨季度 + 优先级 + 人工窗
    def ck(name, got, want):
        print(f"  {'✅' if got == want else '❌'} {name:34s} 得到 {got} / 应为 {want}")
        assert got == want, name
    base = dict(order_cnt=3, amount_12m=8000, orders_12m=3, quarters_12m=2,
                days_since_first_order=400)
    for d, want in [(90, "活跃"), (91, "休眠"), (180, "休眠"),
                    (181, "潜在流失"), (365, "潜在流失"), (366, "流失")]:
        ck(f"闲置 {d} 天", decide(dict(base, idle_days=d))["生命周期"], want)
    ck("实付 14999 不算高价值",
       "高价值" in match(dict(base, idle_days=10, amount_12m=14999)), False)
    ck("实付 15000 含端算高价值",
       "高价值" in match(dict(base, idle_days=10, amount_12m=15000)), True)
    ck("4 单同一季度不算忠诚",
       "忠诚" in match(dict(base, idle_days=10, orders_12m=4, quarters_12m=1)), False)
    ck("潜在流失压过高价值",
       decide(dict(base, idle_days=200, amount_12m=20000))["生命周期"], "潜在流失")
    ck("人工调整 15 天前生效",
       decide(dict(base, idle_days=200, manual_lc="高价值", days_since_manual=15))["生命周期"], "高价值")
    ck("人工调整 35 天前失效",
       decide(dict(base, idle_days=200, manual_lc="高价值", days_since_manual=35))["生命周期"], "潜在流失")
    print("\n✅ 生命周期口径自测通过")
