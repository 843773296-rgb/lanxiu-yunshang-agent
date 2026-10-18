#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把演示世界整体平移到某一天 —— 业务 2026-09-24 定:**世界跟着真实日期走。**

## 为什么

以前这套数据钉在 2026-08-31(seed.py 写死),而机器今天是别的日子。于是:

    问「下一周的订单」→ 按 08-31 算是 09-01~09-07,有 4 单要发货
                      → 按真实今天算是 09-25~10-01,**一条都没有**
    而「一条都没有」和「这家店下周真的没活」在页面上长得一模一样。

用户当场撞到并拍板:**改成跟着真实日期走,每天把世界往前挪一天。**
(我摆过代价:评测基线跨天不可比、历史记录的绝对日期每天在变。他仍然选这个,
 理由是数据要能用 —— 这是他的决定,记在这儿免得以后有人以为是顺手改的。)

## 为什么是「平移」不是「重建」

平移保持**一切相对关系不变**:两单相隔几天、签收满没满 15 天、量体过没过期,
挪多少天都一样。所以:

  · 夹具不会坏(订单号是流水号,不含日期;间隔全都保持)
  · 几秒钟就跑完,而全量重建要几分钟 —— **每天一次的活,得便宜**
  · 数据分布、单量、异常样本一个不少

代价照实说:**历史记录的绝对日期每天在变** —— 今天记着「6 月 1 日那笔退款失败」,
明天它是 6 月 2 日。所以评测基线要记「数据日期」,不同数据日期的两次不许直接比。

## 哪些日期动、哪些不动(**这里有判断,所以是登记制**)

  ① **整列都是日期的** —— 机械识别,全部平移。115 列,判据是「这一列的值 100% 是日期」。
     不用手工登记:新表新列会自动跟上,而**漏掉一列的表现是「这张表停在过去」**,
     不会报错。机械识别在这件事上比手工名单可靠。
  ② **文字里埋着日期的** —— 要人判断,必须登记。判据是:
     **这句话是不是在复述某个结构化日期**。是 → 跟着挪(不挪就和同一行的字段自相矛盾);
     不是 → 不动。
  ③ **来路日期一律不动** —— 「业务 2026-09-20 定」记的是**人哪天拍的板**,
     不是世界里发生的事。世界挪了,人拍板的日子没挪。

⚠️ 没登记又混着日期的列 → **红**。不猜。

## 可以反复跑

meta 里记着世界现在停在哪一天,每次只挪「目标 − 现在」那么多天。
跑两次不会挪两次 —— 第二次的差是 0。
"""
import os, re, sqlite3, sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")
# ⚠️⚠️ **`DB` 是「真库」的定义,命令行的 `--db` 不许重绑它。**
# `tools/oplog_unshift.py` 里 `--db` 是模块级重绑 `DB` 的(那个脚本里没问题),
# 照抄到这里会把下面那道守卫**反过来**:平移末尾 `if 天 and 是真库(db)` 才去跑
# 「按星期重算」,而那几个重算脚本只认死真库、没有 `--db`。
# `DB` 一被重绑成副本路径,判断就成立了 —— **在副本上平移,却去改了真库**,
# 而那是本脚本最不该干的一件事。所以 `--db` 只进 `main`,从参数一路传下去。
# 这套数据当初照哪一天写的 —— 库里还没有 meta 时按它算
基准 = "2026-08-31"


def 是真库(db):
    """`--db` 指的是不是真库本身 —— **按路径指向判,不按字符串相等判**。

    `--db backend/lanxiu.db` 指的就是真库,而它和 `DB`(绝对路径)**字符串不等**。
    用 `db == DB` 的话,这种写法会让「平移后重算」被**静默跳过** ——
    排班还照旧的星期边界排着,而**那种数据看起来完全正常**
    (实测过一次同形的:挪 24 天,周一变周四,8 个人周当场破「每周至少休 1 天」,
     而每一行单看都对)。
    """
    try:
        return os.path.realpath(db) == os.path.realpath(DB)
    except OSError:
        return False


def 标记路径(db):
    """互斥标记跟着**被平移的那个库**走,不跟着 `DB` 走。

    原来写的是 `os.path.dirname(DB)` —— 开了 `--db` 之后那就错了:
    在副本上平移会去占真库的标记,于此同时**真库的每日平移会被一个
    根本没在动真库的进程挡住**,而报错长得和「真有人在平移真库」一模一样。
    副本在别的目录 → 标记落在副本目录,互不相干;
    副本要是放在 `backend/` 里(和真库同目录),两者**本来就该互斥** ——
    同一个目录下同时跑两次平移,`.shifting` 挡住是对的。
    """
    return os.path.join(os.path.dirname(os.path.abspath(db)), ".shifting")

# 整列日期的判据。**要容得下 `2026-02-16 9:16` 这种单位数小时** ——
# 第一版写的是 `\d{2}:\d{2}`,于是 edit_log.ts(542 条)被判成「文字列」漏掉了,
# 而它是一个不折不扣的时间戳列。**格式写严一点点,就会把一整张表留在过去。**
整列日期 = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")
任一日期 = re.compile(r"\d{4}-\d{2}-\d{2}")

# ── 登记:**整列日期、但不许跟着挪**的列 ──────────────────────────────
#
# 2026-10-09 加的。平移器**从格式上分不出**两种日期:
#   · 「世界里发生的事」(订单创建、预约开始)→ 该跟着挪
#   · 「真实世界里什么时候操作的」(运维台账)→ **不该挪**
# 它们都是 `YYYY-MM-DD HH:MM`,在表上长得一模一样。
#
# **而挪它的后果比「日期偏了」更隐蔽**:平移在把这一列 +1 的同时也把
# `world_today` +1,所以「机器时钟 − 世界日期」这个差值**被永久冻住、永不衰减**。
# 实测 `op_log`(4384 行):
#     583 行 @ +31 天  ← 重建刚把世界设回基准(2026-08-31)那会儿写的
#     230 行 @ +1 天   ← 当天平移之前写的
#    3571 行 @ 0 天    ← 平移之后写的
# 于是运维台账里有 813 行**永远停在世界的未来**,而它记的本该是「谁什么时候点了这一下」。
#
# > 一列「故意用真实时钟」的时间,和一列「该跟着世界挪」的日期,
# > **在格式上长得一模一样** —— 平移器认不出区别,
# > 于是把一次性的时钟差变成了**永久偏移**。
#
# ⚠️ `backend/oplog.py` 用机器时钟是**故意的**(注释:台账记运维痕迹,
#    不是演示世界里的事)。两个决定各自都对,**撞在一起才出问题**。
# ⚠️ 这里登记的列**不进 `纯`**,所以不会被 update 碰到;
#    而 `查()` 的自洽判定只对 `max(ordr.created)` vs `world_today`,**不看这些列**,
#    所以排除它们不会让自洽判定红(核过)。
整列日期不挪 = {
    "product.plan_on_shelf":
        "**计划**上新日(新品上市日历读它;用户 2026-10-10 要的)。跟着挪的话,"
        "平移每天把世界和计划**一起**往后推一天,`计划 − 今天` 恒定不变 —— "
        "**那一天永远不会到来**,「每周放 2 件」永远不会发生,**而且没有任何报错**。"
        "(活证明:整库挪 200 天,19 条逾期任务一条不增不减,因为 end_ts 和 world_today 一起挪。)"
        "不挪之后,放出规则是**纯日期驱动**的(`待上架 AND plan_on_shelf <= 世界今天`),"
        "脚本不用记「放到第几件」那种状态,**数据本身就是排期表**。"
        "⚠️ 它也**绝不能**进 backend/worldclock.py 的 `已发生的时间列` —— "
        "那份清单是平移前置闸的判据,计划日期按定义在未来,登记进去的后果是"
        "**每日 05:10 的平移天天失败**,而报错会说「已经发生的事落在未来」",
    "op_log.ts": "操作台账记的是「真实世界里谁什么时候点了这一下」—— 运维痕迹,"
                 "不是演示世界里发生的事(见 backend/oplog.py 的注释:它用机器时钟是故意的)。"
                 "跟着挪会把一次性的时钟差冻成永久偏移",
}

# ── 登记:文字里埋着日期的列,挪还是不挪 ────────────────────────────
文字里也挪 = {
    # 2026-10-15 补的。这张表**之前一条数据都没有**,所以这两列从来没被扫到过 ——
    # 补了 56 份确认书(用户拍:10-10 之后已确认的单要有书面约定)之后它们才显形。
    # > 一个「这一列不含日期」和一个「这张表是空的所以扫不出来」,
    # > **在扫列的结果上长得一模一样。**
    "order_contract.body": "订单确认书正文里写着「确认日期 2026-10-10」,"
                           "复述的就是同一行的 created_at 和这张单的 paid_at —— "
                           "不挪的话,顾客手里那份确认书上的日期和订单确认日期**自相矛盾**;"
                           "和 order_mix_batch.payload(订单快照 JSON)、"
                           "store_report_doc.body(报告正文)同一个道理",
    "factory_msg.reason": "「工厂接单,承诺 2026-09-24 完工」复述的就是同一行的 promise_date —— "
                          "不挪的话,同一条记录里结构化字段和它自己的说明**互相矛盾**",
    "op_log.reason": "派工记录里写着上门时间(「2026-10-04 14:00 → 16:00」),"
                     "它复述的是 task 上的时间",
    "order_mix_batch.payload": "订单快照的 JSON,里面是那一单当时的各个时间点",
    "daily_fresh_batch.原值": "每日上新改一行之前的原值快照(JSON),里面是那一行当时的各个时间点 —— "
                              "和 order_mix_batch.payload 同一个道理:要拿它写回去,"
                              "它就得和那一行现在的日期在同一套世界里",
    "store_report_doc.body": "经营报告正文(店长存的日报 / 周报 / 月报)里写着报告期和各种日期 ——"
                             "同一行的 period_start / period_end 跟着挪,正文不挪就自相矛盾(「上周 9/28—10/4」对不上已经挪过的报告期)",
    "store_report_doc.pack": "保存时冻结的取数包(JSON),里面是那一期的区间、截至日、环比上一期 —— 同上,要和报告期同一套世界",
    # ── 研判草稿里的日期(2026-10-11 登记)──────────────────────────
    # 这五列是**模型写的草稿正文**,里面的日期**全是在复述业务事实**:
    # 「微信支付渠道在 2026-07-12 14:xx 返回…」复述 payment_flow.ts、
    # 「押金于 2026-07-20 10:xx 创建」复述 deposit、
    # 「C21006 建档时间更早(2025-04-11)」复述 customer.created ——
    # 而这几列**都会跟着平移**。草稿不挪的话,**研判结论会引用一个已经不存在的时间**,
    # 而那条结论本身看起来完全正常(四段齐、证据条条有)。
    # > 一条「证据对得上」的研判,和一条「证据指向挪走之前那个世界」的,
    # > **在那四段文字上长得一模一样** —— 只有拿它去对库才看得出来。
    "task.summary": "工单处理记录。10-16 之前 `ops.save_triage()` 把研判根因前 60 字写进这一列"
                    "(之后不再写),现存的仍和 triage.ai_root_cause 是同一句话的两份,还原之前那一列挪这一列就得一起挪",
    "triage.ai_root_cause": "研判根因,复述的是押金 / 支付流水 / 退款轨迹上的时间",
    "triage.ai_action": "建议动作,里面引用具体单据和时间点(「同步最终完成时间戳为 …」)",
    "triage.ai_evidence": "证据清单 —— 逐条列着业务记录的时间,是这五列里日期最密的一列",
    "triage.ai_text": "草稿全文(上面三段的来源),同一个道理",
    "call_audio.consent_basis": "「客户 2025-04-03 接受了服务条款 v2.3」复述的是 terms_accept.accepted_at —— "
                                "那一列跟着挪,这句不挪就自相矛盾(业务拍板日期故意不写进这句,见 recording_terms.默认同意依据)",
    # ── 2026-10-14:造数把「取行集指纹」和「行数」写进 world_meta 之后 ──────
    #
    # `world_meta.v` **以前整列都是日期**(world_today / shifted_at / 基准 /
    # rating_built_on),所以它不在任何登记表里 —— 按「整列日期」默认挪。
    # 往里写了 `rating_rowset_fp`(16 位 hex)和 `rating_rowset_n`(行数)之后,
    # 这一列**就变成「混着日期」了**,于是平移按设计拒绝往下走(不猜)——
    # 而那会让每天 05:10 的定时任务直接失败。
    #
    # 登记在「也挪」这一边,**行为和以前一模一样**:
    # 日期值照旧跟着挪(它们记的就是这个演示世界的日期),
    # 而指纹和行数里一个连字符都没有,`^\d{4}-\d{2}-\d{2}` 匹配不到它们。
    #
    # ⚠️ 这条红**本机门禁结构上抓不到**:本机库的 world_meta 里压根没有这两个键,
    # 因为在共享库上跑造数**等于换考卷**(题集真值就是那批档位),所以从来只在
    # 库副本上跑 —— CI 从零建库才会真写进去。
    # > **本地自证 ≠ 独立复现** —— 本机跑的是同一个旧库。
    # 补法在 `backend/rating_rebuild_check.py`:它在**副本上跑完造数**之后
    # 核一遍这一列的登记状态,这样本机也抓得到。
    "world_meta.v": "这个演示世界的元信息。日期值(world_today / shifted_at / 基准 / "
                    "rating_built_on)记的**就是世界里的日期**,要跟着挪;"
                    "而 rating_rowset_fp / rating_rowset_n 是造数输入的指纹和行数,"
                    "里面没有日期,挪不到它们。"
                    "⚠️ 往这一列再写别的键之前想一句:那个值里有日期吗?"
                    "有、而且不该跟着挪的话,这一条就要重新判",
}
文字里不挪 = {
    "order_contract.terms_ver": "条款版本号 `2026-10-10.2` 记的是**业务哪天拍的板**(来路),"
                                "不是世界里发生的事 —— 世界挪了,人拍板那天没挪。"
                                "跟着挪的话,同一份条款会每天换一个版本号,"
                                "而「版本变了」正是用来判断条款改没改的那个信号;"
                                "同 color_family.note / craft.src_name",
    "daily_fresh_batch.batch": "批次号 `daily_fresh/<日期>` 记的是**哪一次跑的**(那一天的世界日期)——"
                               "是来路,不是世界里发生的事。跟着挪的话,昨天那一批会被今天的"
                               "`批次(今天)` 认成自己那一批、当场回滚掉 —— "
                               "**而「昨天造的数据被撤掉」和「今天什么都没造」在行数上长得一模一样**",
    "color_family.note": "「(业务 2026-09-20 定)」是**来路** —— 记的是人哪天拍的板,"
                         "不是世界里发生的事。世界挪了,人拍板那天没挪",
    "craft.src_name": "出处名里的「用户 2026-10-11 在国家标准全文公开系统核对」是**来路** —— 记的是谁哪天核过出处,"
                      "不是世界里发生的事(同 craft.detail)。2026-10-11 补 GB/T 26380 出处时带进来的;"
                      "没登记的话 shift_world 见到「混着日期却没登记的列」会整个拒绝平移,每日定时任务和 CI 重建都停在这一步",
    "craft.detail": "工艺 / 面料的说明从知识库生成,里面的「(`业务 2026-10-09 统一口径`)」是**来路** ——"
                    "记的是哪天拍的板,不是世界里发生的事(同 color_family.note)。"
                    "10-09 香云纱改口径时带进来的,本地库没重建所以没看见,CI 从零建当场停住",
    "triage.guard_violations": "交付前检查扣下答案时的原话,里面的日期是**来路** ——"
                               "实测唯一一处是「业务 2026-09-24 定:不让价」,"
                               "记的是人哪天拍的板,不是世界里发生的事(同 color_family.note)。"
                               "⚠️ 它和同一张表的 ai_* 五列**分在两边**,不是漏登记:"
                               "那五列是模型复述业务事实,这一列是闸复述业务规矩的出处",
    "truth.expected_evidence": "同上,标注答案里写着依据是哪天定的;"
                               "而且这是标注答案表,内容本身就不该跟着数据动",
    # ── 2026-10-12 清理研判队列里那批「已超时几千小时」时带进来的两列 ──────
    # 处理记录写的是「演示数据清理(用户 2026-10-12 指示),非真实复核」,
    # 那个日期是**来路** —— 记的是用户哪天给的指示,不是世界里发生的事。
    # ⚠️ 这一条逼出一个值得写下来的区分:
    # > **库里的日期有两种 —— 演示世界的日期(要跟着每天平移)和
    # > 真实世界的日期(一个字都不许动)。而它们在一列文本里长得一模一样。**
    # 挪它等于**改写来路**:明天那句会变成「用户 2026-10-13 指示」,
    # 而用户并没有在 13 号说过什么。
    "rating.handle_note": "差评处理记录。里面的日期只出现在「演示数据清理(用户 2026-10-12 指示)」"
                          "那一批上(2026-10-12 清页面时带进来的),是**来路** —— "
                          "记的是用户哪天给的指示,不是世界里发生的事(同 color_family.note)。"
                          "⚠️ 人工写的那些处理记录本来不带日期;"
                          "哪天有人往里写了世界日期(比如「约了 10-15 回店」),"
                          "这一条就要重新判 —— **那时候挪和不挪都错一半**",
    "escalation.reason": "研判升级时发起人写的原因(2026-10-17 起)。和 triage.human_note 同一类:"
                         "人写的一句话,里面要是出现日期,复述的是「哪天拍的 / 哪天说的」,是**来路**",
    "escalation.return_note": "接收人退回升级时写的理由,同 escalation.reason",
    "triage.human_note": "研判销账时人工写的那一句。日期同样只出现在那批演示清理上,是**来路**。"
                         "⚠️ 它和同一张表的 `guard_violations` 分在同一边,理由也一样:"
                         "都是复述「人哪天拍的 / 哪天给的指示」,不是世界里发生的事",
}

# ── 平移之后必须**重算**的东西 ───────────────────────────────────
# 平移保住的是「相隔几天」,保不住「星期几」—— 挪 24 天,周一变成周四。
# 凡是按**星期**编排的数据,平移之后都不再成立,必须重跑一遍。
# 2026-09-24 实测:排班表当场红了 8 个人周(「每人每周至少休 1 天」)——
# 不是数据坏了,是周的边界挪了,而原来那张表是照旧的边界排的。
#
# ⚠️ 新增任何「按星期/按月/按季度」编排的数据,都要加进这张表。
# 漏了的表现是:**平移之后那条业务规则静默地不成立了**,而数据看起来完好。
平移后重算 = [
    ("tools/backfill_roster.py", "排班按星期编排(每周至少休一天、周末排满),星期一变就不成立"),
    ("tools/clamp_future_done.py", "旅程按「第 N 天」排事件,排到最后几张会越过今天 —— "
                                   "于是出现 status=完成、完工日在下周的单"),
    # ⚠️ 上面那一步挪了订单和量体的日期,而「这一单挂的是哪次接待」是按**同一天**认的 ——
    # 必须重挂一遍,再重算影响力。2026-09-24 漏了这两步,6 张单的接待挂到了远程量体上。
    ("tools/backfill_link.py", "接待按「同一天 + 同一个人」认,日期一动就得重挂"),
    ("tools/backfill_wattr.py", "W 型影响力按挂上的接待算,重挂之后要跟着重算"),
]

咬合 = [
    ("把整列日期的判据改严(不认 `9:16` 这种单位数小时)", "每一列混着日期的都登记过了"),
    ("平移之后世界的最后一天对不上目标日期", "世界的最后一天 = 目标日期"),
    ("同一个目标跑两次,被挪了两次", "跑第二次不会再挪"),
    ("把一列没登记的文字日期列加进来", "每一列混着日期的都登记过了"),
    # 2026-10-18:「自不自洽」和「能不能挪」拆成两个问题之后,**死锁会不会回来**
    # 全靠下面这一条守着 —— 少了它,把那个条件去掉就又是「越旧越不肯挪」。
    ("把「太旧」那条的「只问能不能挪」条件去掉(两个问题又混回一个 —— 死锁回来)",
     "问「能不能挪」→ **要说能挪**"),
    ("把「不认识的参数就拒跑」那道守卫删掉(拼错一个字母就跳过自检直接挪)",
     "参数拼错了要拒跑"),
]


def _挪一个(s, 天):
    """保持原样式地挪:`2026-08-31` → `2026-09-24`,`2026-02-16 9:16` 的单位数小时也留着。"""
    m = 整列日期.match(s.strip())
    if not m: return s
    头 = s.strip()[:10]
    try: d = date.fromisoformat(头) + timedelta(days=天)
    except ValueError: return s
    return d.isoformat() + s.strip()[10:]


def _挪文字(s, 天):
    def f(m):
        try: return (date.fromisoformat(m.group(0)) + timedelta(days=天)).isoformat()
        except ValueError: return m.group(0)
    return 任一日期.sub(f, s)


def 扫列(c):
    """返回 (整列日期的, 混着日期的)。只看 TEXT 里的值,不猜列名。

    **按列名猜(`*_at`、`*_date`)会同时犯两种错**:漏掉 `roster.d` 这种,
    又把 `content.published`(有可能是布尔)当成日期。看值不看名。
    """
    纯, 混 = [], []
    for (t,) in c.execute("select name from sqlite_master where type='table'").fetchall():
        try: cols = [d[1] for d in c.execute(f'pragma table_info("{t}")')]
        except sqlite3.Error: continue
        for col in cols:
            try:
                vs = [r[0] for r in c.execute(
                    f'select "{col}" from "{t}" where "{col}" is not null limit 400')]
            except sqlite3.Error: continue
            vs = [v for v in vs if isinstance(v, str) and v.strip()]
            if not vs: continue
            if all(整列日期.match(v.strip()) for v in vs): 纯.append(f"{t}.{col}")
            elif any(任一日期.search(v) for v in vs): 混.append(f"{t}.{col}")
    return 纯, 混


def 现在停在哪天(c):
    try:
        r = c.execute("select v from world_meta where k='world_today'").fetchone()
        if r: return r[0]
    except sqlite3.Error:
        pass
    return 基准


def 平移(db=DB, 到=None, 说=print):
    到 = 到 or date.today().isoformat()   # 真实时钟:这个脚本的活就是「把世界挪到今天」,要挪到哪天只能问时钟;想钉住就传 --到 或设 LANXIU_SEED_TODAY
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS world_meta(k TEXT PRIMARY KEY, v TEXT)")
    现 = 现在停在哪天(c)
    天 = (date.fromisoformat(到) - date.fromisoformat(现)).days
    纯, 混 = 扫列(c)
    漏 = [x for x in 混 if x not in 文字里也挪 and x not in 文字里不挪]
    if 漏:
        return dict(错=f"有 {len(漏)} 列混着日期却没登记过,**不猜**:{漏}")
    说(f"  世界现在停在 {现},要挪到 {到} —— 差 {天} 天")
    if 天 == 0:
        说("  已经在这一天了,不动。")
        c.execute("INSERT OR REPLACE INTO world_meta VALUES('shifted_at',?)",
                  (datetime.now().isoformat(timespec="seconds"),))   # 真实时钟:记的是「什么时候跑的这次平移」,本来就该是真时间
        c.commit(); c.close()
        return dict(到=到, 天=0, 列=len(纯) + len(文字里也挪), 改=0)
    # **只挪这次真的扫到的那几列。** 登记表里写着、库里却没有的(列改过名、
    # 或者这是个还没建全的库),不许照着名字去 update —— 那会当场炸,
    # 而且炸在事务中间。登记表里多出来的另报,见下面那句 warn。
    # ── 动手之前:已经在未来的记录,**不许被继续往后推** ──────────────
    # 2026-09-26 踩到:一条按机器时钟写的 schedule.assigned_at 落在世界的未来,
    # 平移把它**又往后挪了一天** —— 这个 bug **不会自愈**:平移每跑一次就多推一天。
    # 而第二天的红看起来和今天一样,于是真正的原因(某个写口用了机器时钟)
    # 会被当成「数据又漂了」。
    #
    # ⚠️ 判据**调 worldclock.未来记录()**,不去解析 spec_check 的输出。
    # 第一版就是解析文本的,而它挂在 `❌  C4`(两个空格)上 ——
    # 实际输出是一个空格,**闸整个没生效,还让并行会话去追了一个不存在的 bug**。
    # 判据贴着别人的排版,就是贴着一件随时会变的事。
    _sys_path_added = False
    try:
        _b = os.path.join(ROOT, "backend")
        if _b not in sys.path: sys.path.insert(0, _b); _sys_path_added = True
        import worldclock as _WC
        _分 = _WC.分类(c, 基准=现)
        # ⚠️ **这道闸只拦一件事:真的有「已经发生的事」落在未来。**
        # 「表/列查不了」**不在这道闸的职责里** —— 那是「清单和库对不上」,
        # 归 spec_check 的 C4(它在真库上会红,而且必须红:被吞掉的异常和
        # 「查过了没问题」在输出上完全一样)。
        #
        # 第一版把两件事混成一条,结果这个脚本的**自测被自己的闸拦住了**:
        # 合成夹具只有 4 张表、列也不全,于是「查不了」一大片 ——
        # 而那只说明夹具小,不说明有未来记录。
        # **一道闸兼办两件事,它就会在其中一件上判错。**
        未来 = _分["未来行"]
        没查到 = len(_分["缺表"]) + len(_分["查不了"])
        if 没查到:
            说(f"  ℹ 有 {没查到} 列这次没查到(表或列不在 —— 夹具、还没建全的库,"
              f"或者清单和库对不上)。**这不代表那几列没问题** ——"
              f"清单对不对由 spec_check 的 C4 管")
    except Exception as _e:
        # 查不了**不静默放行** —— 说清楚是「没查」,不是「没问题」
        说(f"  ⚠ 平移前的「未来记录」检查没跑起来({type(_e).__name__}: {_e})—— "
          f"**这不代表没有未来记录,只代表没查**")
        未来 = []
    if 未来:
        c.close()
        return dict(错=("平移前发现 %d 条「已经发生的事」落在世界的未来:%s。"
                       "平移会把它们**再往后推 %d 天**,而这个 bug 不会自愈。"
                       "先修写它的那个口 —— 判据是:那一列会不会被平移;"
                       "会的话必须用 backend/worldclock.py 的世界时钟写。"
                       % (len(未来), 未来[:3], 天)))

    该挪文字 = [x for x in 混 if x in 文字里也挪]
    丢 = [x for x in 文字里也挪 if x not in 混]
    if 丢: 说(f"  ⚠ 登记过却没扫到的文字列:{丢} —— 列改名了?还是这批数据里恰好没有日期?")
    # ⚠️ **登记为「不挪」的整列日期,从这次要挪的清单里剔掉,而且明写出来。**
    # 静默剔掉的话,这份名单会慢慢变成一个没人记得的洞 ——
    # 而「它被剔掉了」和「它从来没被扫到」在输出上长得一模一样。
    不挪了 = [x for x in 纯 if x in 整列日期不挪]
    纯 = [x for x in 纯 if x not in 整列日期不挪]
    if 不挪了:
        说(f"  · 不挪(登记过):{不挪了}")
        for x in 不挪了:
            说(f"      {x} —— {整列日期不挪[x][:60]}")
    # 登记过却没扫到的也要报:列改名 / 这张表还没建 / 它已经不是纯日期列了
    没扫到 = [x for x in 整列日期不挪 if x not in 不挪了]
    if 没扫到:
        说(f"  ⚠ 登记为「不挪」却没扫到的:{没扫到} —— 列改名了?表还没建?"
           f"**别当成「已经不用管了」** —— 它可能又变成会被挪的样子了")
    改 = 0
    with c:
        for 名 in 纯 + 该挪文字:
            t, col = 名.split(".", 1)
            rows = c.execute(f'select rowid, "{col}" from "{t}" where "{col}" is not null').fetchall()
            挪 = _挪一个 if 名 in 纯 else _挪文字
            批 = [(挪(v, 天), rid) for rid, v in rows if isinstance(v, str)]
            批 = [(nv, rid) for nv, rid in 批 if nv is not None]
            c.executemany(f'update "{t}" set "{col}"=? where rowid=?', 批)
            改 += len(批)
        c.execute("INSERT OR REPLACE INTO world_meta VALUES('world_today',?)", (到,))
        c.execute("INSERT OR REPLACE INTO world_meta VALUES('shifted_at',?)",
                  (datetime.now().isoformat(timespec="seconds"),))   # 真实时钟:同上,这是运维痕迹不是世界里的事
        c.execute("INSERT OR REPLACE INTO world_meta VALUES('基准',?)", (基准,))
    说(f"  挪了 {改} 个值,{len(纯)} 个日期列 + {len(该挪文字)} 个文字列")
    c.close()
    # 按星期编排的数据要重算 —— 见上面「平移后重算」那张表
    # ⚠️ 副本上**故意不重算**:那几个脚本只认死真库(没有 `--db`),
    # 在副本上跑它们等于「平移副本却改了真库」。但跳过不许静默 ——
    # 一个「排班重算过的库」和一个「排班还是旧星期边界的库」,
    # **在行数和每一行上都长得一模一样**,只在那条业务规则上不成立。
    if 天 and not 是真库(db):
        说(f"  ⏭ 副本({db})—— **跳过「按星期重算」**:"
          f"{[x for x, _ in 平移后重算]} 只认死真库,在副本上跑等于去改真库。"
          f"代价是这个副本里按**星期**编排的数据(排班、按第 N 天排的旅程)"
          f"还是旧的边界 —— 拿副本验那类判据会红,**那是副本的局限,不是数据坏了**")
    if 天 and 是真库(db):
        import subprocess
        for 脚本, 为什么 in 平移后重算:
            说(f"  ↻ 重算 {脚本}({为什么})")
            r = subprocess.run([sys.executable, os.path.join(ROOT, 脚本)],
                               capture_output=True, text=True, cwd=ROOT, timeout=300)
            if r.returncode:
                说(f"  ❌ {脚本} 没跑成:{(r.stderr or r.stdout)[-300:]}")
                return dict(错=f"{脚本} 重算失败 —— 平移已经落库,但按星期编排的数据还是旧的")
    return dict(到=到, 天=天, 列=len(纯) + len(该挪文字), 改=改)


def 世界今天(db=DB):
    """**运行时的「今天」要从库里读,不是从时钟读。**

    如果今天没重建/没平移,库还停在前天 —— 这时候按时钟说「今天」,
    就又回到了当初那个错位:说的日子和数据里的日子不是一天。
    """
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        r = c.execute("select v from world_meta where k='world_today'").fetchone()
        c.close()
        if r: return r[0]
    except sqlite3.Error:
        pass
    return None


# ── 自洽检查(check.sh 里跑) ──────────────────────────────────────
def 查(db=DB, 说=print, 只问能不能挪=False):
    """四件事:**每一列含日期的都登记过**、库说自己停在哪天、数据实际停在哪天、离真实今天差几天。

    **前两件对不上就是红的** —— 那说明有一列日期没跟着挪(或者有人手改了库),
    而它的表现是「某张表停在过去」,不会报错。
    第三件是**提醒不是错**:几天没平移不是代码坏了,是该跑一下了;
    差太久(> 14 天)**在「自不自洽」这个问题下**当红的算 ——
    那时候「下周没有单」这种假空又会回来。

    ⚠️⚠️ **而「太旧」在「能不能挪」这个问题下不算错**(`只问能不能挪=True`)。
    2026-10-18 用户拍的 B 案:这两个问题原来混成了一个,造出一个**死锁** ——
    `tools/daily_shift.sh` 的第 ⑤ 条是「开跑前先自检,不自洽就不挪」
    (意图:往一个半平移的库上再挪一次,只会得到一个更说不清的库),
    而「太旧」算进了不自洽,于是机器关两周之后:
    落后 > 14 天 → 自检红 → **拒绝平移** → 继续落后 → **永远红**,
    日志里每天写一行「开跑前就不自洽,这次不挪」,只有人手跑一次才解得开。

    > 一个「这个库坏了,不能挪」和一个「这个库好着,只是太旧了」,
    > **在那个非零退出码上长得一模一样。**

    根源是分类错误:「有日期没跟着挪 / 有人手改过库」是**库坏了**(该拒绝再挪),
    而「数据停在 46 天前」是**库好着只是旧了** —— **那恰恰是该挪的理由**。
    所以这不是闸太严,是把该挪的理由放进了「不能挪」的清单。

    两个问题分开之后:`--check` 仍然把「太旧」报成错(人看,提醒一条不丢),
    `--can-shift` 只验库坏没坏(自动平移看)。

    ⚠️⚠️ **第一件是 2026-10-09 加的,因为它的代价要到第二天凌晨才看得见。**
    `平移()` 遇到没登记的混着日期的列会**当场拒绝往下走**(「不猜」)——
    那是对的。但在那之前**没有任何东西会提醒你**:
    那天我加了一张 `daily_fresh_batch`(两列含日期:批次号和原值 JSON),
    本地门禁 241 条全绿、CI 也全绿 —— 而**第二天早上 05:10 的定时任务会直接失败**。
    > 一张「我加的表」和一张「会把每日平移卡死的表」,
    > **在门禁的绿勾上长得一模一样** —— 因为那时候没有任何判据去跑一次平移。
    现在这一条在门禁里红,当天就看得见。
    (并行会话 2026-10-09 提的:「这条最好也落进检查,别只写在交接里」——
     而这个项目反复栽在「教训记下来了而没落到判据上」。)
    """
    坏 = []
    if not os.path.exists(db):
        说("  ⚠ 还没有库(没重建过)—— 跳过"); return []
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    # ── ⓪ 每一列含日期的都登记过(见文档字符串) ─────────────────────
    纯列, 混列 = 扫列(c)
    漏列 = [x for x in 混列 if x not in 文字里也挪 and x not in 文字里不挪]
    if 漏列:
        坏.append(f"有 {len(漏列)} 列混着日期却**没登记过**:{漏列} —— "
                  f"`平移()` 会当场拒绝往下走,也就是**第二天 05:10 的定时任务直接失败**。"
                  f"往 `文字里也挪` 或 `文字里不挪` 里加一条(带理由)")
    else:
        说(f"  ✅ 每一列含日期的都登记过(纯日期列 {len(纯列)} · 文字里带日期 {len(混列)})")
    # 登记过却没扫到的只**提醒**,不算红:那张表可能还没建,或者这批数据里恰好没有日期
    没了 = ([x for x in 文字里也挪 if x not in 混列]
            + [x for x in 文字里不挪 if x not in 混列]
            + [x for x in 整列日期不挪 if x not in 纯列])
    if 没了:
        说(f"  ⚠ 登记过却没扫到的:{没了} —— 列改名了?表还没建?"
           f"**别当成「不用管了」**(它可能又变成会被挪的样子了)")
    # ── ⓪b 整列日期列里的值,**SQLite 的 `date()` 必须解析得出来** ──────────
    # 2026-10-10 栽到:`max(ordr.created)` 是 `2026-10-10 20:68`(68 分钟),
    # `date()` 解析不了就返回 **NULL**,于是 `link_check` 的
    # `hired_at >= date(max(ordr.created),'-180 day')` **永不为真** ——
    # 报「半年内入职的顾问 0 人」,而库里明明有(工号 60000015,世界今天前 60 天)。
    #
    # > 一句「这个库没有新人样本」和一句「最后一张订单的时间戳非法」,
    # > **在那条检查的输出上长得一模一样** —— 而它说的是第一句。
    #
    # **而且它是间歇的**:`max(created)` 随每日上新变,最大那行哪天恰好非法就红,
    # 所以同一份代码 8416e14 绿、4609198 红,中间没人碰过入职日期。
    # 两个源头都修了(`daily_fresh` 的分钟十位、`seed.py` 的小时没补零),
    # 存量 330 行由 `tools/fix_bad_timestamps.py` 修过 —— 这一条是**不许再回来**。
    #
    # ⚠️ 判据用的是 **SQLite 自己的 `date()`**,不是我们写的正则:
    # 会咬人的那个解析器就是 SQLite 的那个,拿别的正则去判等于判了另一件事
    # (`2026-02-16 9:16` 我们的正则认、`date()` 不认 —— 正是那 296 行)。
    坏值 = []
    for 名 in 纯列:
        t, col = 名.split(".", 1)
        try:
            n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NOT NULL '
                          f'AND date("{col}") IS NULL').fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            坏值.append(f"{名}({n} 行)")
    if 坏值:
        坏.append(f"有 {len(坏值)} 列的值 **SQLite 的 date() 解析不出来**:{坏值[:6]} —— "
                  f"这种值会让任何 `date(列)` 的比较**静默变成 NULL**,"
                  f"而拿它当门槛的检查会报 0 而不是报错。"
                  f"跑 `python3 tools/fix_bad_timestamps.py --做`;"
                  f"**同时要去修写它的那个口**,不然明天又回来")
    else:
        说(f"  ✅ {len(纯列)} 个整列日期列的值,SQLite 的 date() 都解析得出来")
    说自己 = 现在停在哪天(c)
    有meta = bool(c.execute("select name from sqlite_master where type='table' and name='world_meta'").fetchone())
    if not 有meta:
        坏.append("库里没有 world_meta —— 这个库是平移上线之前建的,跑一次 tools/shift_world.py")
        c.close(); [说(f"  ❌ {x}") for x in 坏]; return 坏
    try:
        实际 = (c.execute("select max(created) from ordr").fetchone() or [None])[0]
    except sqlite3.Error:
        实际 = None
    c.close()
    说(f"  库说自己停在 {说自己};订单里最后一条是 {实际}")
    if 实际 and 实际[:10] != 说自己:
        坏.append(f"世界的最后一天({实际[:10]})和库里记的 world_today({说自己})对不上 —— "
                  f"**有日期没跟着挪**,或者有人手改过库")
    差 = (date.today() - date.fromisoformat(说自己)).days   # 真实时钟:这条检查问的就是「数据离今天差几天」,不问时钟没法答
    if 差 > 14 and not 只问能不能挪:
        坏.append(f"数据停在 {说自己},离今天 {差} 天 —— 太久了,"
                  f"「下周一条单都没有」这种假空会回来。跑:python3 tools/shift_world.py")
    elif 差 > 14:
        # 问的是「能不能挪」:旧**不是**不能挪的理由,挪正是要修它的那个动作
        说(f"  ⚠ 数据比今天早 {差} 天(> 14)—— 在「能不能挪」这个问题下**不算错**,"
          f"这一挪就是来修它的")
    elif 差 > 0:
        说(f"  ⚠ 数据比今天早 {差} 天 —— 该跑一次 `python3 tools/shift_world.py` 了(不算错)")
    else:
        说(f"  ✅ 世界和真实日期同一天")
    for x in 坏: 说(f"  ❌ {x}")
    return 坏


# ── 自测 ─────────────────────────────────────────────────────────
def _自测():
    import tempfile
    过, 挂 = [], []
    def ck(名, 真, 补=""):
        (过 if 真 else 挂).append(名)
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:130]) if 补 else ''}")

    p = os.path.join(tempfile.mkdtemp(), "t.db")
    c = sqlite3.connect(p)
    c.executescript("""
      create table ordr(id text, created text, note text);
      create table edit_log(ts text);
      create table factory_msg(at text, reason text);
      create table color_family(note text);
    """)
    c.execute("insert into ordr values('D1','2026-08-31 19:58','没有日期的说明')")
    c.execute("insert into ordr values('D2','2026-08-01 09:00','也没有')")
    c.execute("insert into edit_log values('2026-02-16 9:16')")      # 单位数小时
    c.execute("insert into factory_msg values('2026-08-20','工厂接单,承诺 2026-09-05 完工')")
    c.execute("insert into color_family values('黛是青黑色(业务 2026-09-20 定)')")
    c.commit()

    ck("单位数小时的时间戳算「整列日期」(不算文字)",
       "edit_log.ts" in 扫列(c)[0], 扫列(c))
    c.close()

    r = 平移(p, "2026-09-24", 说=lambda *a: None)
    c = sqlite3.connect(p)
    ck("世界的最后一天 = 目标日期",
       c.execute("select max(created) from ordr").fetchone()[0][:10] == "2026-09-24",
       c.execute("select max(created) from ordr").fetchone()[0])
    ck("时刻留着(不是只挪日期)",
       c.execute("select max(created) from ordr").fetchone()[0].endswith("19:58"))
    ck("单位数小时的格式没被改写",
       c.execute("select ts from edit_log").fetchone()[0].endswith(" 9:16"),
       c.execute("select ts from edit_log").fetchone()[0])
    ck("间隔不变(两单原来差 30 天,现在还是 30 天)",
       (date.fromisoformat(c.execute("select max(created) from ordr").fetchone()[0][:10])
        - date.fromisoformat(c.execute("select min(created) from ordr").fetchone()[0][:10])).days == 30)
    ck("文字里复述的日期跟着挪了",
       "2026-09-29" in c.execute("select reason from factory_msg").fetchone()[0],
       c.execute("select reason from factory_msg").fetchone()[0])
    ck("来路日期**没有**被挪(业务哪天拍的板)",
       "2026-09-20" in c.execute("select note from color_family").fetchone()[0],
       c.execute("select note from color_family").fetchone()[0])
    c.close()

    r2 = 平移(p, "2026-09-24", 说=lambda *a: None)
    ck("跑第二次不会再挪", r2["天"] == 0, r2)
    c = sqlite3.connect(p)
    ck("跑两次之后最后一天还是目标日期",
       c.execute("select max(created) from ordr").fetchone()[0][:10] == "2026-09-24")

    # 没登记的文字日期列 → 拒绝动手
    c.execute("create table 新表(说明 text)")
    c.execute("insert into 新表 values('这条里有 2026-05-05 但没人登记过')")
    c.commit(); c.close()
    r3 = 平移(p, "2026-09-25", 说=lambda *a: None)
    ck("每一列混着日期的都登记过了(没登记就拒绝动手)",
       "没登记过" in (r3.get("错") or ""), r3.get("错"))
    c = sqlite3.connect(p)
    ck("拒绝动手时一个值都没改",
       c.execute("select max(created) from ordr").fetchone()[0][:10] == "2026-09-24")
    c.close()

    # ── `--db`:在副本上动手,不许碰到真库 ──────────────────────────
    # 这三条守的是同一件事的两个方向,**两个方向错的代价都不可见**:
    #   往「没认出真库」偏 → 真库上的「按星期重算」被静默跳过(排班悄悄不成立)
    #   往「把副本认成真库」偏 → 在副本上平移,却去改了真库
    ck("--db 写成相对路径也认得出是真库(不然真库上的「按星期重算」会被静默跳过)",
       是真库(os.path.join(ROOT, "backend", "..", "backend", "lanxiu.db")) is True)
    ck("--db 指向别的库就不算真库", 是真库(p) is False)
    ck("互斥标记跟着被平移的那个库走,不跟着真库走",
       标记路径(p) == os.path.join(os.path.dirname(p), ".shifting")
       and 标记路径(p) != 标记路径(DB))

    # 副本上平移:**明说跳过了重算**。静默跳过的话,
    # 「重算过的库」和「排班还是旧星期边界的库」在每一行上都长得一样。
    p2 = os.path.join(tempfile.mkdtemp(), "t2.db")
    c = sqlite3.connect(p2)
    # 具名列 —— 门禁的「位置参数只许少不许多」那条棘轮当场咬住了第一版
    c.executescript("create table ordr(id text, created text);"
                    "insert into ordr(id, created) values('A','2026-08-31 10:00');")
    c.commit(); c.close()
    话 = []
    r4 = 平移(p2, "2026-09-20", 说=话.append)
    ck("副本上平移会明说「跳过按星期重算」(不静默)",
       not r4.get("错") and any("跳过" in x for x in 话), r4)

    # ── 「自不自洽」和「能不能挪」必须是两个问题(2026-10-18 用户拍的 B 案)──
    # 这三条合起来才算验住:**旧但好 → 能挪**、**坏 → 不能挪**、而提醒一条不丢。
    # 少了第二条,死锁就回来了;少了第三条,它会去挪一个半平移的库。
    from datetime import timedelta as _td
    def _造世界(停在, 实际=None):
        q = os.path.join(tempfile.mkdtemp(), "w.db")
        k = sqlite3.connect(q)
        k.executescript("create table ordr(id text, created text);"
                        "create table world_meta(k text primary key, v text);")
        k.execute("insert into world_meta(k,v) values('world_today',?)", (停在,))
        k.execute("insert into ordr(id,created) values('D1',?)",
                  ((实际 or 停在) + " 10:00",))
        k.commit(); k.close()
        return q

    _哑 = lambda *a, **kw: None
    _旧 = (date.today() - _td(days=46)).isoformat()   # 真实时钟:这三条验的就是「离真实今天差几天」那条检查,而它本身只能问时钟(见 查() 里同样标注的那一行);不用真实时钟造不出「旧了 46 天」这个场景
    _旧库 = _造世界(_旧)
    _坏全 = 查(_旧库, 说=_哑)
    _坏挪 = 查(_旧库, 说=_哑, 只问能不能挪=True)
    ck("数据旧了 46 天,问「自不自洽」→ **要说不自洽**(这个提醒不能丢)",
       any("太久了" in x for x in _坏全), _坏全)
    ck("同一个库,问「能不能挪」→ **要说能挪**(旧不是坏,而挪正是修它的动作)",
       not _坏挪, _坏挪)
    _歪库 = _造世界(_旧, 实际=(date.today() - _td(days=3)).isoformat())   # 真实时钟:同上,要造的是「库记的那天和数据实际那天对不上」,两个日期都得相对真实今天摆
    _坏歪 = 查(_歪库, 说=_哑, 只问能不能挪=True)
    ck("库真不自洽(记的那天和数据实际那天对不上),问「能不能挪」→ **也要说不能**",
       any("对不上" in x for x in _坏歪), _坏歪)

    # ── 「不认识的参数就拒跑」那道守卫 ────────────────────────────────────
    # **真去跑一次自己**(不在这儿重实现一份判断)—— 守卫活在 `__main__` 里,
    # 而这个脚本**不带参数时会真的去平移**:守卫没了,拼错一个字母就不是
    # 「先自检再挪」,而是「跳过自检直接挪」,而两者在「它挪了」上长得一模一样。
    import subprocess as _sp
    _r = _sp.run([sys.executable, os.path.abspath(__file__), "--can-shif"],
                 capture_output=True, text=True, timeout=180)
    ck("参数拼错了要拒跑(退出码 2),不许当成「没这个参数」接着去平移",
       _r.returncode == 2 and "不认识这些参数" in (_r.stdout + _r.stderr),
       f"退出码 {_r.returncode}")

    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    # ⚠️ **不认识的参数一律拒跑。** 这个脚本**不带参数时的动作是「真的去平移」** ——
    # 所以把 `--can-shift` 拼错一个字母,它不会报错,会**跳过自检直接挪**。
    # > 一个「自检通过了所以挪」和一个「参数没认出来、自检压根没跑就挪」,
    # > **在「它挪了」这件事上长得一模一样。**
    # (2026-10-18 加 `--can-shift` 时顺手堵的:新参数给 bash 调用,
    #  而这个仓库为 bash 栽过四次 —— 中文参数名在 launchd 的 locale 下还可能变形,
    #  所以那个参数**另留了一个纯 ASCII 的名字**,定时任务用 ASCII 那个。)
    _认得的参数 = {"--selftest", "--db", "--check", "--能不能挪", "--can-shift",
                "--到", "--to"}
    _野参数 = [a for a in sys.argv[1:] if a.startswith("-") and a not in _认得的参数]
    if _野参数:
        print(f"\033[31m❌ 不认识这些参数:{_野参数}\033[0m")
        print("   **不认识就不跑** —— 这个脚本不带参数时会真的去平移,"
              "静默忽略一个拼错的参数等于「跳过自检直接挪」。")
        print(f"   认得的:{sorted(_认得的参数)}")
        sys.exit(2)
    if "--selftest" in sys.argv: sys.exit(_自测())
    # ── `--db`:对哪个库动手 ───────────────────────────────────────
    # 开它是为了**在副本上做端到端**(整库挪几百天,看判码/分布守不守恒)——
    # 以前要另搭一套临时目录才做得到,于是那条欠账一直挂着。
    # 解析放在这里(不是模块级),理由见文件开头 `DB` 那段:重绑 `DB` 会反掉守卫。
    库 = DB
    for i, a in enumerate(sys.argv):
        if a == "--db" and i + 1 < len(sys.argv): 库 = sys.argv[i + 1]

    if "--能不能挪" in sys.argv or "--can-shift" in sys.argv:
        # 自动平移开跑前问的就是这一个问题:**这个库坏没坏**(坏了再挪更说不清)。
        # 「数据旧不旧」不在这个问题里 —— 旧是该挪的理由,见 `查()` 的 docstring。
        print("演示世界 · 能不能挪" + ("" if 是真库(库) else f"(副本 {库})") + "\n" + "=" * 76)
        坏 = 查(库, 只问能不能挪=True)
        rc = _自测()      # 代码本身坏了也不该挪
        print()
        if 坏 or rc:
            print(f"\033[31m❌ 这个库现在不能挪:{len(坏)} 处不自洽\033[0m"); sys.exit(1)
        print("\033[32m✅ 能挪(库是自洽的;旧不旧不在这个问题里)\033[0m")
        sys.exit(0)
    if "--check" in sys.argv:
        print("演示世界的日期 · 自洽检查" + ("" if 是真库(库) else f"(副本 {库})") + "\n" + "=" * 76)
        坏 = 查(库)
        rc = _自测()
        print()
        if 坏 or rc:
            print(f"\033[31m❌ 世界日期 {len(坏)} 处不符合预期\033[0m"); sys.exit(1)
        print("\033[32m✅ 世界日期自洽\033[0m")
        sys.exit(0)
    到 = None
    for i, a in enumerate(sys.argv):
        if a in ("--到", "--to") and i + 1 < len(sys.argv): 到 = sys.argv[i + 1]
    到 = 到 or os.environ.get("LANXIU_SEED_TODAY") or date.today().isoformat()   # 真实时钟:同上,CI 和复现靠 LANXIU_SEED_TODAY 钉住

    # ── 互斥标记 ──────────────────────────────────────────────────
    # ⚠️ 这一条是并行会话(eureka-c5)2026-09-26 指出来的,而它是对的:
    # 这个脚本一次要重写 **115 个日期列 / 32 万个值**,中途被别人读到的库
    # 是**平移到一半的库** —— 而「库坏了」和「库正在被平移」长得一模一样。
    # `tools/rebuild.sh` 早就有 `.rebuilding` 标记,这里一直没有;
    # 而「谁都能直接敲这一行」和 09-18 栽的那三次是同一形状:
    # **调用方的守卫只护得住调用方。**
    标记 = 标记路径(库)
    老 = None
    if os.path.exists(标记):
        try: 老 = int(open(标记).read().strip())
        except Exception: 老 = None
    if 老 is not None:
        活着 = True
        try: os.kill(老, 0)
        except (ProcessLookupError, PermissionError): 活着 = (老 is not None and False)
        except Exception: 活着 = True
        if 活着:
            print(f"❌ 另一个平移正在跑(pid {老})—— 两个同时改同一个库,"
                  f"只会得到一个日期对不上的库,而它看起来完全正常")
            sys.exit(1)
        # 进程没了但标记还在 = 上一次被中断了。**这时候库可能是半平移的**,
        # 所以不静默接着跑:让人先跑 --check 看一眼。
        print(f"⚠️ 有一个残留的平移标记(pid {老} 已经不在了)——"
              f"**上一次可能被中断在一半**。\n"
              f"   先跑 `python3 tools/shift_world.py --check` 看世界自不自洽;"
              f"确认没问题再删掉 {标记} 重跑。")
        sys.exit(1)
    open(标记, "w").write(str(os.getpid()))
    import atexit as _atexit
    _atexit.register(lambda: os.path.exists(标记) and os.remove(标记))

    print(f"把演示世界平移到 {到}" + ("" if 是真库(库) else f" · 副本 {库}"))
    print("=" * 76)
    r = 平移(db=库, 到=到)
    if r.get("错"):
        print(f"\033[31m❌ {r['错']}\033[0m")
        print("   新加的表/列里有日期就要在 tools/shift_world.py 里登记:"
              "复述结构化日期的跟着挪,记「业务哪天定的」的不挪")
        sys.exit(1)
    print(f"\033[32m✅ 世界现在停在 {r['到']}\033[0m")
