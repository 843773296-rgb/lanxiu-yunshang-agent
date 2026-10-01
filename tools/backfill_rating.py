#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铺签收后的顾客评价 —— **业务 2026-09-27 拍的形状:门店拉开差距 + 有趋势。**

⚠️ **这个文件本来叫 `tools/seed_rating.py`,和 `backend/seed_rating.py`(建表)撞名了。**
两个同名模块,`import seed_rating` 取到哪一个**完全取决于 sys.path 谁在前面** ——
而且**不报错**:它安静地导入了另一个,直到用到一个不存在的属性才炸
(`backend/rating_check.py` 去读 `门店均分`,拿到的是建表那个模块)。
按仓库既有约定改名成 `backfill_*`(同 `backfill_color` / `backfill_scene`):
**往已有数据上补一层**,正是这个脚本干的事。

口径在 `knowledge/rating.py`,表在 `backend/seed_rating.py`,写口在 `backend/rating_write.py`。

## 业务拍的(用户 2026-09-27 选的方案 C)

    三家店的平均分   静安旗舰店 4.7 · 徐汇店 4.5 · 杭州湖滨店 4.2
    最近三个月趋势   7月 4.4 → 8月 4.5 → 9月 4.6(缓慢上升)

**为什么要拉开差距**:铁律 TK13 写着「这个星级唯一能比的是本店历史趋势和门店之间」。
三家店造成一样的话,**那句话在数据上没有对象** —— 模型说「门店之间可以比」,
店长点进去看到三个几乎相同的数字。

⚠️ **用户明确知道并接受的代价(原样记在业务拍板里)**:
> 形状是我按「杭州店交付慢」编的因,**业务没说过哪家店差**。
所以这三个数**不是业务事实,是演示形状**。谁要拿它去讲「杭州店有问题」,那是把演示当结论。

## 为什么不走写口(和签收那条线的欠账不是一回事)

`rating_write.customer_rate` 用 `worldclock.当下()` 写 `rated_at`,而且
`能不能评` 会拿「签收满没满 7 天」去挡 —— **它按设计只能写出「今天的评价」**。
而这批数据要覆盖过去 11 个月的签收,**走写口写不出历史**。

> 这和签收那条线的欠账**不同**:那边写口能用而造数没用(3330 个签收只有 31 条码痕迹);
> 这边是写口按设计写不出历史。所以这里直接 INSERT,**但口径全走 `knowledge/rating.py`**
> (`是差评` / `差评待办`),让造出来的数据和写口**用同一份规矩**。
> 抄一份判据在这儿的话,写口改了线、造数不跟着改,而两边都不会报错。

## 确定性

固定种子。**同一份代码跑两次结果一样** —— 否则「数据变了」和「代码变了」分不清。
可反复跑:每次先删掉自己造的那些(评价 + 评价差评工单),再重铺。
"""
import collections, datetime as dt, os, random, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import rating as R
import worldclock

DB = os.path.join(ROOT, "backend", "lanxiu.db")
种子 = 20260927

# ── 业务 2026-09-27 拍的形状 ───────────────────────────────────────────
评价率 = 0.50                    # 签收过的包裹里,有多少留下了评价
门店均分 = {"SH001 静安旗舰店": 4.7, "SH002 徐汇店": 4.5, "SH003 杭州湖滨店": 4.2}
默认均分 = 4.5

# ── 最近三个月的趋势:**绝对月目标**,不是相对加成 ──────────────────────
# ⚠️ 第一版写成「相对加成 -0.10 / 0 / +0.10」,**趋势根本没造出来**:
# 实测 7月 4.50 → 8月 4.51 → 9月 4.56,而 5 月是 4.66(比 9 月还高)。
# 两个原因叠在一起:
#   ① **每个月的门店构成不同** —— 5 月静安店占比高,门店效应盖过了月趋势;
#   ② 每月约 190 条,星级采样的标准误约 0.05,**0.2 的跨度淹在噪声里**。
# 这是「造了但没盯着」的标准形态:我以为造出了趋势,其实没有,
# **而它在页面上看不出来** —— 一串 4.5 左右的数字。
# 修法:改成绝对目标 + 把跨度加到 0.3,并且**加一道检查盯住它**(rating_check 的形状那几条)。
月目标 = {"2026-07": 4.35, "2026-08": 4.50, "2026-09": 4.65}
月基线 = 4.45                    # 这三个月之前的月份用它 —— 让「最近三个月上升」真的成立
# 门店偏移相对**全年的平均月目标**算,不手写。
# ⚠️ 原来手写 `全店基准 = 4.5`,而全年有 9 个月走 4.45 的基线、三个月 4.35/4.50/4.65 ——
# 全年平均约 4.46,**每家店都系统性偏低 0.04**。杭州店拍的 4.2 本就贴着容差下沿(±0.15),
# 世界每天平移、抽样跟着变,2026-10-01 那天的抽样掉出下沿 0.01,门禁红。
# **两个应该相等的数分两处写,差的那 0.04 不会报错,只会让最紧的那家店某天突然红。**
全店基准 = round((月基线 * (12 - len(月目标)) + sum(月目标.values())) / 12, 4)
改过的比例 = 0.03                # 多少条评价被顾客改过一次(24 小时内)
# ── 差评关掉的概率:**按年龄递增** ─────────────────────────────────────
# ⚠️ 第一版是一个固定的 90%,结果 **13 条差评挂了 90 天以上、最老 279 天**。
# 那不违反任何规则,但它在**讲一个故事**:「店长九个月没处理过一条差评」。
# 这和门店差距是同一个性质的东西 —— 拿演示数据讲业务没说过的事;
# 区别是门店差距**用户拍过、知情**,而「积压九个月」是我随手造出来的,没人拍过。
# 真实的待处理清单应该**以最近的为主**:老的要么早处理完了,要么早就爆了。
# (天数, 已关闭的概率)—— 从上往下第一条命中的为准
关闭概率 = [(7, 0.15), (30, 0.80), (90, 0.97), (10**6, 0.995)]
形状_依据 = ("门店 4.7/4.5/4.2 + 三个月上升趋势 —— **业务 2026-09-27 选的方案 C**;"
           "用户同时知情:这三个数是**演示形状,不是业务事实**(业务没说过哪家店差)")


# ── 评语池 ────────────────────────────────────────────────────────────
#
# ⚠️ 第一版差评只有 5 句、好评 5 句(含一句空的),于是待处理清单上
# **3 条评语一模一样、1 条是空的**。数据没错(最近 7 天真的就 3 条差评),
# 但**演示时店长看到的是同一句话出现三次** —— 那不像真实的顾客反馈。
# 业务 2026-09-27 下午拍:**只把评语写丰富,条数和形状一个都不动。**
#
# 分五类,因为这个星级衡量的是**交付体验**(口径里那一条):
# 尺寸合不合身、工期准不准、到店接待、包装、面料手感 —— **不写「衣服质量不好」**,
# 顾客签收当场还没穿过,那种评语本身就不成立(写进去等于给评测喂一个错口径的样本)。
差评评语 = {
    "尺寸": ["腰围比说的紧", "袖长短了一截", "肩线偏了,穿上不太正", "裙长比量的短",
             "领口卡脖子", "袖口偏紧,抬手勒着"],
    "工期": ["等了两周才到,有点久", "说好周五到,拖到下周二", "比承诺的晚了九天",
             "催了两次才发货", "婚期前一天才到,太赶了"],
    "接待": ["到店没人接待,等了半小时", "导购一直在忙别的客人", "取件时找不到人核码",
             "问了三次才说清怎么取", "到店才知道要本人来"],
    "包装": ["包装压皱了", "外箱破了个角", "没有防尘袋", "折痕很重,回家得熨",
             "配饰散在箱子里没固定"],
    "面料": ["面料摸着有点硬", "里料起静电", "线头没剪干净", "袖口线头多",
             "熨烫痕迹还在"],
}
好评评语 = ["很合身,导购很细心", "准时拿到,满意", "做工好看", "试穿就很合身",
            "比预期好,下次还来", "导购帮着调了袖长,很到位", "包装很用心",
            "刚好赶上婚期", "颜色和图上一样", "到店取很方便", "第一次定制,体验不错",
            "细节做得扎实", "工期比想的快"]
# 空评语的比例:**差评几乎都会写字**(有情绪才评),好评常常只点星不写话。
没写话的概率 = {"差评": 0.08, "好评": 0.30}


def _星级分布(均分):
    """给定目标平均分,给一个「当面评」该有的形状 —— **偏高、长尾在低分**。

    ⚠️ 不是按均分反解一个漂亮的分布,而是在两个锚点之间插值:
      4.2 那一头差评(≤3)约 14%,4.75 那一头约 4%。
    业务定的偏差是「当面难给差评」,所以 **5 星占大头、1 星极少**,
    而不是正态分布 —— 正态会在 3 星堆起一座山,那是匿名事后评的形状。
    """
    # 高端锚点 2026-10-01 从 ≈4.88 抬到 ≈4.91:全店基准改成按全年月目标现算(4.4625)之后,
    # 静安店 9 月的目标是 4.65+0.2375≈4.89,超出 4.88 会被夹 —— 自测「没有发生静默夹逼」当场抓到
    低 = {5: 0.42, 4: 0.30, 3: 0.16, 2: 0.08, 1: 0.04}       # ≈ 3.98
    高 = {5: 0.93, 4: 0.057, 3: 0.008, 2: 0.003, 1: 0.002}   # ≈ 4.91
    def 均(d): return sum(k * v for k, v in d.items()) / sum(d.values())
    a, b = 均(低), 均(高)
    t = (均分 - a) / (b - a)
    if t < 0 or t > 1:
        # ⚠️ **夹逼要说话。** 第一版锚点是 4.14~4.75,而「静安店 9 月」的目标是
        # 4.65+0.2=4.85、「杭州店 7 月」是 4.35-0.3=4.05 —— 两头都被
        # `max(0,min(1,t))` **静默夹掉**,于是门店差距被压扁(4.63/4.45/4.30,
        # 而业务拍的是 4.7/4.5/4.2),**而输出上看不出发生过夹逼**。
        # 这和「收下星级不许把 6 星夹成 5 星」是同一条:我在判据上守住了它,
        # 却在造数里犯了 —— 所以现在夹了要记一笔,跑完一起报。
        _夹过.append(round(均分, 2))
        t = max(0.0, min(1.0, t))
    out = {k: 低[k] * (1 - t) + 高[k] * t for k in 低}
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


_夹过 = []
# 每条评价「挑目标时用的是哪个月」—— 自测用的缝:
# 这个口径错过一次(按签收月挑、检查按评价月分组),而它表现成「造数有系统性偏差」,
# 靠统计判很难判(要 67% 的跨月比例才动得过容差)。**直接记下来,直接比。**
_用的月 = {}


def _挑星(rng, 分布):
    x, acc = rng.random(), 0.0
    for 星 in (5, 4, 3, 2, 1):
        acc += 分布[星]
        if x <= acc:
            return 星
    return 5


def 铺(db=DB, 说=print):
    _夹过.clear(); _用的月.clear()
    rng = random.Random(种子)
    今 = worldclock.今天()
    今s = 今.isoformat()
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row

    # 先清掉自己造的 —— 可反复跑
    n旧 = c.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
    c.execute("DELETE FROM task WHERE type=?", (R_工单类型 := "评价差评",))
    c.execute("DELETE FROM rating")

    # ⚠️ 四条资格,一条都不能少:
    #   ① 真签收过(至少一件合身,而且有 fit_at)—— 判据和写口那道闸同一个事实
    #   ② 签收**不在世界的未来**(19 个曾经在,已由 clamp_future_done 挪回来)
    #   ③ 包裹没作废
    #   ④ 客户没被匿名化 —— 人的数据都擦了,名下还挂着评价说不通
    #      (order_spread_check 有一条同源的:已匿名化的客户名下没有订单)
    包 = [dict(r) for r in c.execute("""
        SELECT t.pkg_id, MAX(t.fit_at) 签收于, k.order_id, o.customer_id, o.shop,
               (SELECT t2.fit_verified_by FROM pickup_item t2
                 WHERE t2.pkg_id=t.pkg_id AND t2.fit_result='合身'
                   AND t2.fit_verified_by IS NOT NULL LIMIT 1) 顾问
          FROM pickup_item t JOIN pkg k ON k.pkg_id=t.pkg_id
          JOIN ordr o ON o.id=k.order_id JOIN customer u ON u.id=o.customer_id
         WHERE t.fit_result='合身' AND t.fit_at IS NOT NULL AND k.void_at IS NULL
           AND u.phone NOT LIKE 'DELETED-%'
         GROUP BY t.pkg_id HAVING substr(MAX(t.fit_at),1,10) <= ?
         ORDER BY t.pkg_id""", (今s,))]
    if not 包:
        说("  ❌ 一个能评的包裹都没有 —— **这是「没扫到东西」,不是「都铺好了」**")
        return 1

    # ── 为什么**不**做「构成校正」(试过,撤了)──────────────────────────
    # 2026-09-27 CI 红过一次:趋势本地 +0.29、**CI 从零重建只有 +0.08**。
    # 根因是「每个月的门店构成不一样」——9 月杭州店(分低)占比高,整体月均被拉低。
    # 我先加了构成校正(让每月的**加权平均**命中月目标),趋势稳了,
    # 但自测当场抓到代价:**门店差距被吃掉**(0.23,应 0.5),还触发了静默夹逼
    # (极端构成下目标算到 5.0 和 3.97,超出星级分布能表达的范围)。
    #
    # 这是**数学上的两难**,不是 bug:「每月整体平均」是各店的加权和,
    # 构成一变,想让它命中目标就得牺牲「每店整体平均」。
    #
    # > 真正的答案在铁律 TK13 里已经写着:**这个星级能比的只有「本店历史」和「门店之间」。**
    # > 「本店自己 7 月 → 9 月 上升」才是那个不被构成污染的说法;
    # > 而「全店整体月均」正是它警告过的那种被构成搅乱的数 ——
    # > 极端情况下每家店都在涨、整体却在跌(辛普森悖论)。
    #
    # 所以造数就按 `月目标 + 门店偏移` 老老实实写,**判据改成按店内部比**
    # (见 `_自测` 和 `backend/rating_check.查形状`)。
    # 整体月均照旧报出来,但**不拿它当判据** —— 报而不判,理由写在检查里。
    行, 工单 = [], []
    for p in 包:
        if rng.random() > 评价率:
            continue
        # 「签收当场就请」—— 评价时间 = 签收之后几分钟到几小时,极少数隔一天
        签 = dt.datetime.strptime(p["签收于"][:16], "%Y-%m-%d %H:%M")
        评于 = 签 + dt.timedelta(minutes=rng.choice([3, 5, 8, 12, 20, 45, 90, 240,
                                                    60 * 20, 60 * 30]))
        if 评于.date() > 今:                     # 不许落到世界的未来
            评于 = 签 + dt.timedelta(minutes=5)
        评s = 评于.strftime("%Y-%m-%d %H:%M")
        # ⚠️ **月份取「评价月」,不是「签收月」。**
        # 2026-09-27 量到一个系统性偏差:7 月三家店里两家偏高(+0.13/+0.06)、
        # 9 月三家全偏低(-0.18/-0.12/-0.24)。不是噪声 —— 是**两处口径不一致**:
        # 这里原来按 `签收月` 挑目标,而检查按 `rated_at` 的月份分组。
        # 于是 8-31 签收、9-01 评价的那些,目标按 8 月给(低)却被数进 9 月,
        # 把 9 月往下拽;同理 6 月漏进 7 月(基线 4.45 > 7 月目标 4.35)把 7 月往上抬。
        # **一份数据两处口径,而它表现成「造数有系统性偏差」。**
        ym = 评s[:7]
        _用的月[p["pkg_id"]] = (ym, 评s[:7])
        # 目标 = 这个月的目标 + 这家店的偏移(偏移相对 全店基准 算)
        均 = 月目标.get(ym, 月基线) + (门店均分.get(p["shop"], 默认均分) - 全店基准)
        星 = _挑星(rng, _星级分布(均))
        # 差评先挑一类再挑一句 —— 这样五类都会出现,而不是某一类被随机数吃掉
        if R.是差评(星):
            类 = rng.choice(sorted(差评评语))
            评语 = "" if rng.random() < 没写话的概率["差评"] else rng.choice(差评评语[类])
        else:
            评语 = "" if rng.random() < 没写话的概率["好评"] else rng.choice(好评评语)
        # 改过的那一小撮:24 小时内改一次
        改次, 改于, 原星 = 0, None, None
        if rng.random() < 改过的比例:
            原星 = 星
            星 = max(1, min(5, 星 + rng.choice([-2, -1, 1, 2])))
            # ⚠️ **改了星级,评语要跟着换。**
            # 第一版是先挑评语、后改星级,于是待处理清单上出现了
            # `3 星 · 「到店取很方便」` —— **好评评语挂在差评上**。
            # 真实顾客把 5 星改成 2 星,不会留着「很方便」那句话。
            # 而这条数据**在页面上看起来完全正常**:一个星级、一句话,各自都合法。
            if R.是差评(星) != R.是差评(原星):
                if R.是差评(星):
                    类 = rng.choice(sorted(差评评语))
                    评语 = "" if rng.random() < 没写话的概率["差评"] else rng.choice(差评评语[类])
                else:
                    评语 = "" if rng.random() < 没写话的概率["好评"] else rng.choice(好评评语)
            if 星 != 原星:
                改次 = 1
                改 = 评于 + dt.timedelta(hours=rng.choice([1, 3, 6, 12, 20]))
                if 改.date() > 今:
                    # 兜底也不许越过今天 —— 晚上 23 点评的,+1 小时就是明天(2026-10-01 C4 红过一条)
                    改 = min(评于 + dt.timedelta(hours=1), dt.datetime.combine(今, dt.time(23, 59)))
                改于 = 改.strftime("%Y-%m-%d %H:%M")
            else:
                原星 = None
        # 差评 → **走口径模块**建待办,不在这儿抄一份判据
        待 = R.差评待办(星, 评语, p["order_id"], p["pkg_id"], 评s, 顾问=p["顾问"])
        tid = 处理于 = 处理人 = 处理记录 = None
        if 待:
            tid = f"TR{p['pkg_id']}"
            岁 = (今 - dt.date.fromisoformat(评s[:10])).days
            关了 = rng.random() < next(p for d, p in 关闭概率 if 岁 <= d)
            工单.append((tid, R_工单类型, p["pkg_id"], "已关闭" if 关了 else "待处理",
                        评s, f"{星} 星差评:{(评语 or '(顾客没写评语)')[:40]}"))
            if 关了:
                h = dt.datetime.strptime(评s, "%Y-%m-%d %H:%M") + dt.timedelta(
                    days=rng.choice([0, 1, 1, 2, 3]), hours=rng.choice([1, 3, 6]))
                if h.date() > 今:
                    # ⚠️ 兜底也要封顶到今天:原来是「评价后 2 小时」,而 22 点后评的差评 +2 小时就过了午夜 ——
                    # 10-01 那天一条处理时间落在 10-02 00:01,门禁 C4 红。封顶到今天 23:59,不早于评价时间
                    h = min(dt.datetime.strptime(评s, "%Y-%m-%d %H:%M") + dt.timedelta(hours=2),
                            dt.datetime.combine(今, dt.time(23, 59)))
                处理于 = h.strftime("%Y-%m-%d %H:%M")
                处理人 = p["顾问"]        # 演示数据里用经手工号占位;真处理人是店长
                处理记录 = rng.choice([
                    "已电话联系顾客,约了本周回店免费修线头,顾客接受",
                    "已电话回访,顾客反映等太久,已说明工期并赠送一次保养",
                    "已上门取件返修,修好后顺丰寄回,顾客确认满意",
                    "已联系顾客,腰围按实测重新调整,免费返修",
                    "已致电致歉,包装问题已反馈工厂,下次改进"])
        行.append((p["pkg_id"], p["order_id"], p["customer_id"], 星, 评语 or None, 评s,
                  R.来源_顾客 if hasattr(R, "来源_顾客") else "顾客小程序",
                  p["顾问"], 改次, 改于, 原星, tid, 处理于, 处理人, 处理记录))

    c.executemany("""INSERT INTO rating(pkg_id,order_id,customer_id,star,note,rated_at,src,
                        advisor_no,edit_cnt,edited_at,star_before,task_id,
                        handled_at,handled_by,handle_note)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", 行)
    c.executemany("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
                  工单)
    # ⚠️ **记下造数时世界停在哪天。**
    # 2026-09-27 CI 连红两次,根因是这个脚本在 `rebuild.sh` 里排在 `shift_world` **之前**:
    # `seed.py` 重建之后世界回到建库基准日(2026-08-31),造数按「8 月」给月度目标,
    # 随后平移 +27 天把那批评价**挪成了 9 月** —— 而目标是按 8 月给的。
    # 改顺序能修这一次,但**防不住下一个人再挪回来**,所以把「造数时的世界日期」记下来,
    # 由 `backend/rating_check.py` 断言它和现在的世界日期一致。
    c.execute("CREATE TABLE IF NOT EXISTS world_meta(k TEXT PRIMARY KEY, v TEXT)")
    c.execute("INSERT OR REPLACE INTO world_meta VALUES('rating_built_on',?)", (今s,))
    c.commit()

    # ── 自己证明干了活,而且形状对得上 ──────────────────────────────
    import statistics as st
    星们 = [r[3] for r in 行]
    差 = [x for x in 星们 if R.是差评(x)]
    说(f"  评价 {len(行)} 条(可评包裹 {len(包)} 个 · 评价率 {len(行)/len(包):.0%})"
      f"{f' · 清掉旧的 {n旧} 条' if n旧 else ''}")
    说(f"  平均 {st.mean(星们):.2f} 星 · 差评(≤{R.差评线}) {len(差)} 条 {len(差)/len(星们):.0%}"
      f" · 顾客改过 {sum(1 for r in 行 if r[8])} 条")
    待处理 = sum(1 for t in 工单 if t[3] == "待处理")
    说(f"  差评工单 {len(工单)} 张:待处理 {待处理} · 已关闭 {len(工单)-待处理}"
      f"(关闭概率按年龄递增:7 天内 {关闭概率[0][1]:.0%} → 90 天以上 {关闭概率[-1][1]:.1%})")
    by = {}
    for r, p in zip(行, [x for x in 包 if x["pkg_id"] in {y[0] for y in 行}]):
        pass
    店 = {}
    for r in c.execute("""SELECT o.shop, COUNT(*) n, AVG(r.star) a FROM rating r
                          JOIN ordr o ON o.id=r.order_id GROUP BY o.shop ORDER BY 3 DESC"""):
        店[r["shop"]] = (r["n"], r["a"])
        说(f"    {r['shop']:18s} {r['n']:5d} 条  平均 {r['a']:.2f}"
          f"(业务拍的 {门店均分.get(r['shop'], 默认均分)})")
    说("  最近三个月(业务拍的 7月 4.35 → 8月 4.50 → 9月 4.65 这个方向):")
    for r in c.execute("""SELECT substr(rated_at,1,7) ym, COUNT(*) n, AVG(star) a FROM rating
                          WHERE rated_at>='2026-07' GROUP BY ym ORDER BY ym"""):
        说(f"    {r['ym']}  {r['n']:4d} 条  平均 {r['a']:.2f}")
    if _夹过:
        说(f"  ⚠️ 有 {len(_夹过)} 次目标超出星级分布能表达的范围,被夹到边界"
          f"(例:{sorted(set(_夹过))[:4]})—— **形状会被压扁,而输出上看不出来**,"
          f"所以这里报出来。要么调 门店均分/月目标,要么把 _星级分布 的两个锚点拉开")
    说("  ⚠️ 门店之间的差距和这条趋势都是**演示形状,不是业务事实** —— "
      "业务没说过哪家店差、也没说过在变好(用户知情)")
    c.close()
    return 0


# ── 自测:**合成夹具**,证明形状真的造得出来 ────────────────────────────
#
# 为什么要有它:`backend/rating_check.py` 的形状那几条守的是**真库**,
# 而给它写咬合会撞上两件事:
#   ① 咬合**不会重新造数** —— 库里还是已经铺好的数据,改造数脚本压根不影响检查结果;
#   ② 改 `门店均分` 这个常量会**同时改掉检查的期望值**(检查就是从它读的),
#      于是红的是「平均分不贴合」,不是「差距被弄平」—— **红的不是那一条**。
# 所以形状要在这儿独立证明:造三家店 × 三个月的合成签收,铺一遍,看差距和趋势出不出来。
def _自测():
    import tempfile, statistics as st
    挂 = []

    def ck(名, 真, 补=""):
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:110]) if 补 else ''}")
        if not 真: 挂.append(名)

    p = os.path.join(tempfile.mkdtemp(prefix="rat-"), "t.db")
    c = sqlite3.connect(p)
    c.executescript("""
      create table ordr(id text primary key, customer_id integer, shop text, kind text);
      create table customer(id integer primary key, phone text);
      create table pkg(pkg_id text primary key, order_id text, void_at text);
      create table pickup_item(order_item_id integer primary key, order_id text, pkg_id text,
                               fit_result text, fit_at text, fit_verified_by text);
      create table task(id text primary key, type text, ref_id text, status text,
                        created text, summary text);
    """)
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    import seed_rating as _建
    _建.建表(c)
    # 三家店 × 三个月,**而且每个月的门店构成故意失衡**。
    #
    # ⚠️ 失衡是**有意的**:2026-09-27 CI 红过一次(趋势本地 +0.29、CI 只 +0.08),
    # 根因是「每个月的门店构成不一样」把趋势吃掉了。
    # 第一版夹具每月三家店各 600 —— **完全均衡**,于是它测不出这个失效:
    # 没有构成校正照样过。**夹具要构造出会失败的那个状态**,所以这里让
    # 7 月偏静安(分高的店)、9 月偏杭州(分低的店) —— 不校正的话趋势会被抹平甚至反向。
    #
    # ⚠️ 第一版是 200,自测当场挂在「徐汇店贴着 4.5」上(实测 4.68,偏 +0.18)——
    # 我一开始以为造数有系统性偏差,查下来是**样本量不够**:
    # 每店每月约 100 条进了评价,星级标准差约 0.9 → **标准误 0.09**,
    # 而我把容差卡在 ±0.12 —— **容差比噪声还紧,测的就是噪声不是形状**。
    # 600 之后每店约 900 条,标准误降到 0.03,±0.12 才真的在测形状。
    # (真库那边反而没这个问题:每店 400~800 条,标准误 0.035。)
    # (月, 日, {店: 签收数})—— 7 月偏静安、9 月偏杭州,**和趋势方向相反**
    构成 = [
        ("2026-07", "2026-07-15", {"SH001 静安旗舰店": 1000, "SH002 徐汇店": 500,
                                   "SH003 杭州湖滨店": 200}),
        ("2026-08", "2026-08-15", {"SH001 静安旗舰店": 600, "SH002 徐汇店": 600,
                                   "SH003 杭州湖滨店": 600}),
        ("2026-09", "2026-09-15", {"SH001 静安旗舰店": 200, "SH002 徐汇店": 500,
                                   "SH003 杭州湖滨店": 1000}),
        # ⚠️ **月底签收**:评价时间最多 +30 小时,所以这批会有一部分落到下个月。
        # 第一版夹具所有签收都在 15 号,**评价永远不跨月** ——
        # 于是「目标按签收月还是评价月挑」这个 bug 它一次都测不出来。
        # **夹具没有跨月的行,那条判据就是空转的。**
        ("2026-07底", "2026-07-31", {"SH001 静安旗舰店": 120, "SH002 徐汇店": 120,
                                     "SH003 杭州湖滨店": 120}),
        ("2026-08底", "2026-08-31", {"SH001 静安旗舰店": 120, "SH002 徐汇店": 120,
                                     "SH003 杭州湖滨店": 120}),
    ]
    k = 0
    for ym, 日, 分配 in 构成:
        for shop, n in 分配.items():
            for _ in range(n):
                k += 1
                c.execute("insert into customer values(?,?)", (k, f"1380000{k:05d}"))
                c.execute("insert into ordr values(?,?,?,'定制品订单')", (f"O{k}", k, shop))
                c.execute("insert into pkg values(?,?,null)", (f"P{k}", f"O{k}"))
                c.execute("insert into pickup_item values(?,?,?,'合身',?,'S001')",
                          (k, f"O{k}", f"P{k}", f"{日} " + ("22:30" if "底" in ym else "15:00")))
    c.commit(); c.close()

    import types
    _s = types.ModuleType("seed"); _s.TODAY = "2026-09-27"
    sys.modules["seed"] = _s
    import importlib; importlib.reload(worldclock)
    说过 = []
    rc = 铺(db=p, 说=说过.append)
    ck("铺得出来(退出码 0)", rc == 0, 说过[:1])
    c = sqlite3.connect(p); c.row_factory = sqlite3.Row
    店 = {r["shop"]: r["a"] for r in c.execute(
        """select o.shop, avg(r.star) a from rating r join ordr o on o.id=r.order_id
           group by o.shop""")}
    for shop, 目标 in sorted(门店均分.items()):
        ck(f"{shop} 造出来贴着 {目标}(±0.12)", abs(店[shop] - 目标) <= 0.12,
           f"实际 {店[shop]:.2f}")
    跨 = max(店.values()) - min(店.values())
    应 = max(门店均分.values()) - min(门店均分.values())
    ck(f"门店之间真的拉开了(应 {应:.1f},至少六成)", 跨 >= 应 * 0.6, f"实际 {跨:.2f}")
    # ⚠️ 趋势判据和 `backend/rating_check.查形状` **同一套**:
    # 按店配对后合并当主判据,每店单独只判方向(每店每月样本小,判不了幅度)。
    # 这个夹具的门店构成是**故意失衡**的 —— 正好证明配对能去掉构成的影响。
    店月 = {(r["shop"], r["ym"]): (r["n"], r["a"]) for r in c.execute(
        """select o.shop, substr(r.rated_at,1,7) ym, count(*) n, avg(r.star) a from rating r
           join ordr o on o.id=r.order_id group by 1,2""")}
    有 = sorted(月目标)
    应升 = 月目标[有[-1]] - 月目标[有[0]]
    差们 = []
    for shop in sorted(门店均分):
        a, b = 店月.get((shop, 有[0])), 店月.get((shop, 有[-1]))
        ck(f"{shop} 在两端都有评价", bool(a and b))
        if a and b:
            差们.append((shop, b[1] - a[1], a[0] + b[0]))
            ck(f"{shop} 自己没有下滑", (b[1] - a[1]) >= -0.10,
               f"{a[1]:.2f} → {b[1]:.2f}({b[1]-a[1]:+.2f})")
    W = sum(x[2] for x in 差们) or 1
    合 = sum(x[1] * x[2] for x in 差们) / W
    ck(f"**按店配对合并后**在上升(应升 {应升:.2f},至少一半)", 合 >= 应升 * 0.5,
       f"合并升 {合:+.2f}(" + " · ".join(f"{s.split()[-1]} {d:+.2f}" for s, d, _ in 差们) + ")")
    全 = {r["ym"]: r["a"] for r in c.execute(
        """select substr(rated_at,1,7) ym, avg(star) a from rating group by ym""")}
    print("     ℹ 全店整体月均(**报而不判**,构成失衡的夹具上它可能跟趋势反着走):"
          + " → ".join(f"{m} {全[m]:.2f}" for m in 有 if m in 全))
    错月 = [pk for pk, (用, 评) in _用的月.items() if 用 != 评]
    ck("挑目标用的月份 == 这条评价自己的月份(造数和检查一个口径)", not 错月,
       f"{len(错月)} 条对不上:{错月[:3]}" if 错月 else f"{len(_用的月)} 条逐条对过")
    c2 = sqlite3.connect(p); 跨 = c2.execute(
        """select count(*) from rating r join pickup_item t on t.pkg_id=r.pkg_id
            where substr(r.rated_at,1,7) <> substr(t.fit_at,1,7)""").fetchone()[0]; c2.close()
    ck("夹具里**真的有**签收月和评价月不同的行(否则上一条是空转的)", 跨 > 0, f"{跨} 条跨月")
    ck("没有发生静默夹逼(目标都在星级分布能表达的范围内)", not _夹过,
       sorted(set(_夹过))[:4])
    好句 = set(好评评语); 差句 = {x for v in 差评评语.values() for x in v}
    坏语 = [r for r in c.execute("select pkg_id, star, note from rating "
                                 "where note is not null and note<>''")
            if (R.是差评(r["star"]) and r["note"] in 好句)
            or (not R.是差评(r["star"]) and r["note"] in 差句)]
    ck("评语和星级对得上(改过星级的那批,评语也换了)", not 坏语,
       f"{len(坏语)} 条对不上:{[dict(x) for x in 坏语[:2]]}" if 坏语 else "逐条对过")
    ck("差评都建了工单", c.execute(
        "select count(*) from rating where star<=? and task_id is null", (R.差评线,)
    ).fetchone()[0] == 0)
    建于 = (c.execute("select v from world_meta where k='rating_built_on'").fetchone() or [None])[0]
    ck("记下了造数时的世界日期(顺序那道守卫靠它)", 建于 == "2026-09-27",
       f"记的是 {建于} —— `rating_check` 的「造数之后世界没有再被平移过」靠这个值,"
       f"不记就等于那道守卫没有依据")
    ck("一条都没落在世界的未来", c.execute(
        "select count(*) from rating where substr(rated_at,1,10)>'2026-09-27'").fetchone()[0] == 0)
    c.close()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不符合预期:{挂}"); return 1
    print(f"✅ 评价造数自测全过(合成夹具 {k} 个签收,**每月门店构成故意失衡**"
          f" —— 7 月偏静安、9 月偏杭州,和趋势方向相反;不做构成校正的话趋势会被抹平)")
    return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。规格在 tools/bite_specs.json 里可重放,
# 攻击的是 `--selftest`(合成夹具)—— 因为咬合**不会重新造数**,
# 打真库上那份检查是打不到造数路径的。
咬合 = [
    ("让 _星级分布 忽略传入的目标(一律用中间那个分布)", "门店之间真的拉开了"),
    ("让月目标不生效(只按门店偏移算)", "**按店配对合并后**在上升"),
    ("目标按「签收月」挑而不是「评价月」", "挑目标用的月份 == 这条评价自己的月份"),
    ("把夹具里「月底签收」那两组去掉", "夹具里**真的有**签收月和评价月不同的行"),
    ("让「顾客改评价」那一步不换评语", "评语和星级对得上"),
    ("让造数不记「它用的是哪天的世界日期」", "记下了造数时的世界日期"),
    ("把星级分布的插值锚点收窄回 4.14~4.75(两头目标被静默夹掉)", "没有发生静默夹逼"),
    ("让差评不建工单(差评躺在表里,不进待处理清单)", "差评都建了工单"),
]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("评价造数 · 自测(合成夹具,不碰真库)")
        print("=" * 78)
        sys.exit(_自测())
    print("铺签收后的顾客评价")
    print("=" * 78)
    sys.exit(铺())
