#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评价数据的检查 —— 盯住「有评价但没签收」「差评没进清单」这一类。

口径在 `knowledge/rating.py`,写口在 `backend/rating_write.py`。

## 这份检查分两半,第二半不是可选的

**① 真库上的不变量。** 但业务 2026-09-27 定了**造数先别铺**,所以这张表现在是空的 ——
于是这几条判据在真库上**一条都没有被执行过**。
而项目的老规矩是:**「没扫到东西」不是「都通过」**。空表时这里会明确说出来,不冒充绿。

**② 合成夹具上的自证。** 造几行**故意坏掉**的数据,确认每条判据真的会红。
没有这一半的话:

> 判据从写下来那天起没被跑过一次,**而它和「查过了没问题」在输出上一模一样。**

铺数据那天,第一半自然就有东西可查了;而第二半那天照样要留着 ——
它防的是另一件事:**判据被改坏而数据恰好没触发它**。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "tools")]
import rating as R
import worldclock
import backfill_rating as SR   # **形状的那几个数只写一处** —— 在造数脚本里
# ⚠️ 名字是 `backfill_rating` 不是 `seed_rating`:后者和 `backend/seed_rating.py`(建表)
# 撞名,而 `sys.path` 里 backend 在前 —— `import seed_rating` 会**安静地**取到建表那个,
# 直到读 `门店均分` 才炸。**两个同名模块,谁在前面谁赢,而且不报错。**

DB = os.path.join(HERE, "lanxiu.db")
工单类型 = "评价差评"
FAIL, N = [], [0]


def ck(名, ok, 验了, 说=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {名}(验了 {验了} 条){('  ' + str(说)[:150]) if 说 else ''}")
    if not ok: FAIL.append(名)


# ── 判据:每一条都是「查出坏行」,返回坏行清单 ──────────────────────────
# **判据写成函数**,这样真库和合成夹具用的是同一份代码 ——
# 抄两份的话,合成夹具证明的就不是真库上跑的那一份。
def 没签收就评了(c):
    """评价必须晚于(或等于)这个包裹签收那一刻。**跨表的先后,worldclock.序关系 表达不了**
    (那份清单是「同一张表里两列」),所以放在这儿。"""
    return [dict(r) for r in c.execute("""
        SELECT r.pkg_id, r.rated_at, (SELECT MAX(t.fit_at) FROM pickup_item t
                 WHERE t.pkg_id=r.pkg_id AND t.fit_result='合身') 签收于
          FROM rating r
         WHERE 签收于 IS NULL OR r.rated_at < 签收于""")]


def 星级不合法(c):
    return [dict(r) for r in c.execute(
        "SELECT pkg_id, star FROM rating WHERE star IS NULL OR star<? OR star>? OR star<>CAST(star AS INTEGER)",
        (R.星最低, R.星最高))]


def 差评没进清单(c):
    """≤3 星必须有一张 `task` 工单(业务 2026-09-27:**自动进**待处理清单)。"""
    return [dict(r) for r in c.execute(f"""
        SELECT r.pkg_id, r.star, r.task_id FROM rating r
         WHERE r.star<=? AND (r.task_id IS NULL
               OR NOT EXISTS(SELECT 1 FROM task t WHERE t.id=r.task_id AND t.type='{工单类型}'))""",
        (R.差评线,))]


def 好评却挂了工单(c):
    """反向:>3 星不该有差评工单。**只查一个方向的检查会漏掉反向那一半** ——
    而「差评都进了清单」和「清单里全是差评」是两件事。"""
    return [dict(r) for r in c.execute(
        "SELECT pkg_id, star, task_id FROM rating WHERE star>? AND task_id IS NOT NULL "
        "AND star_before IS NULL", (R.差评线,))]        # 顾客从差评改上来的不算(清单故意不撤)


def 工单没有对应的评价(c):
    """`task` 里每条评价差评工单,都要找得到那条评价。**孤儿工单会永远躺在待处理里。**"""
    return [dict(r) for r in c.execute(
        f"SELECT id, ref_id FROM task WHERE type='{工单类型}' "
        f"AND NOT EXISTS(SELECT 1 FROM rating r WHERE r.task_id=task.id)")]


def 关了却没写处理记录(c):
    """已关闭的差评工单必须有处理记录 —— **「看过了」不算处理完**(口径里那一条)。"""
    return [dict(r) for r in c.execute(f"""
        SELECT t.id, r.pkg_id, r.handle_note FROM task t JOIN rating r ON r.task_id=t.id
         WHERE t.type='{工单类型}' AND t.status<>'待处理'
           AND (r.handle_note IS NULL OR LENGTH(TRIM(r.handle_note))<{R.最短处理记录})""")]


def 两处状态打架(c):
    """**和聚合无关的那一条。**

    状态只存 `task.status` 一处,`rating` 只存内容。所以「rating 上写了处理记录、
    工单却还在待处理」是**两边各自说了一套** —— 而这种漂不会报错,
    它只让两个页面显示不同的东西。
    ⚠️ 这条**不看任何汇总字段**:重算什么都骗不过「这两行各写了什么」。
    """
    return [dict(r) for r in c.execute(f"""
        SELECT t.id, t.status, r.pkg_id, r.handled_at FROM task t JOIN rating r ON r.task_id=t.id
         WHERE t.type='{工单类型}' AND t.status='待处理' AND r.handled_at IS NOT NULL""")]


def 来源不对(c):
    """只认顾客自己在小程序提交的 —— **顾问代评的星级不能用来衡量顾问自己**。"""
    return [dict(r) for r in c.execute(
        "SELECT pkg_id, src FROM rating WHERE src IS NULL OR src<>?", (R.来源_顾客 if hasattr(R, "来源_顾客") else "顾客小程序",))]


def 评语和星级对不上(c):
    """好评评语挂在差评上(或反过来)。

    ⚠️ 2026-09-27 真出过:待处理清单上有一条 `3 星 · 「到店取很方便」`。
    根因是造数**先挑评语、后改星级**(「顾客改评价」那一步),
    于是一条 5 星带着好评评语被改成 3 星,评语没跟着换。
    **而这条数据在页面上看起来完全正常**:一个星级、一句话,各自都合法 ——
    只有把两样放在一起看才看得出矛盾。
    """
    好句 = set(SR.好评评语)
    差句 = {x for v in SR.差评评语.values() for x in v}
    坏 = []
    for r in c.execute("SELECT pkg_id, star, note FROM rating "
                       "WHERE note IS NOT NULL AND note<>''"):
        if R.是差评(r["star"]) and r["note"] in 好句:
            坏.append(dict(pkg_id=r["pkg_id"], star=r["star"], note=r["note"], 错="差评挂好评语"))
        elif not R.是差评(r["star"]) and r["note"] in 差句:
            坏.append(dict(pkg_id=r["pkg_id"], star=r["star"], note=r["note"], 错="好评挂差评语"))
    return 坏


def 改过却没留痕(c):
    return [dict(r) for r in c.execute(
        "SELECT pkg_id, edit_cnt, star_before, edited_at FROM rating "
        "WHERE edit_cnt>0 AND (star_before IS NULL OR edited_at IS NULL)")]


# 合成夹具里「这条判据该抓的是哪一行」—— **一行只坏一件事,所以一一对应**。
# ⚠️ 这张表存在的理由:光判「抓到了没有」不够 —— 判据被改成查**别的**条件时,
# 它照样能抓到夹具里另一行,于是**改坏了却没红**(咬合第一次跑就是这么抓到的)。
该抓谁 = {"没签收就评了": "PB", "星级不合法": "PC", "差评没进清单": "PD",
         "好评却挂了工单": "PE", "工单没有对应的评价": "PF",
         "关了却没写处理记录": "PG", "两处状态打架": "PH",
         "来源不对": "PI", "改过却没留痕": "PJ", "评语和星级对不上": "PL"}

判据 = [("没签收就评了", 没签收就评了), ("星级不合法", 星级不合法),
       ("差评没进清单", 差评没进清单), ("好评却挂了工单", 好评却挂了工单),
       ("工单没有对应的评价", 工单没有对应的评价),
       ("关了却没写处理记录", 关了却没写处理记录),
       ("两处状态打架", 两处状态打架), ("来源不对", 来源不对),
       ("评语和星级对不上", 评语和星级对不上),
       ("改过却没留痕", 改过却没留痕)]


def 查一遍(c, 前缀=""):
    n = c.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
    for 名, f in 判据:
        坏 = f(c)
        ck(f"{前缀}{名} —— 一条都没有", not 坏, n, (f"{len(坏)} 条:{坏[:2]}" if 坏 else ""))
    return n


def 查形状(c, n):
    """**铺完必须有东西盯着形状。**

    业务 2026-09-27 拍的是「门店拉开差距 + 最近三个月上升」,而那个形状
    **会被悄悄弄平**:下一次造数改个参数、或者某个脚本重写了 rating,
    门店三个数变得一样 —— 而页面上还是一串 4.5 左右的数字,**看不出来**。

    这条检查当天就抓到过两次:① 月趋势写成相对加成,**趋势根本没造出来**
    (7月 4.50 → 9月 4.56,而 5 月 4.66 比 9 月还高);② 星级分布的插值锚点太窄,
    门店差距被**静默夹平**(4.63/4.45/4.30,而拍的是 4.7/4.5/4.2)。

    ⚠️ 目标值**从 `tools/backfill_rating.py` 读**,不在这儿抄一份 ——
    抄一份就会各自漂,而漂的表现是「检查绿着但形状已经不是业务拍的那个」。
    ⚠️ 判据留了余量(±0.15):每月每店只有一两百条,星级采样的标准误约 0.05,
    **卡太死会天天红,而检查天天红人就不看了。**
    """
    容差 = 0.15
    店 = {r["shop"]: (r["n"], r["a"]) for r in c.execute(
        """SELECT o.shop, COUNT(*) n, AVG(r.star) a FROM rating r
           JOIN ordr o ON o.id=r.order_id GROUP BY o.shop""")}
    for shop, 目标 in sorted(SR.门店均分.items()):
        got = 店.get(shop)
        if not got:
            ck(f"{shop} 有评价", False, 0, "这家店一条评价都没有"); continue
        ck(f"{shop} 平均分贴着业务拍的 {目标}(±{容差})",
           abs(got[1] - 目标) <= 容差, got[0], f"实际 {got[1]:.2f}")
    if len(店) >= 2:
        分 = sorted(x[1] for x in 店.values())
        拍 = sorted(SR.门店均分.values())
        应差 = 拍[-1] - 拍[0]
        ck(f"门店之间真的拉开了差距(业务拍的跨度 {应差:.1f},至少要有它的六成)",
           (分[-1] - 分[0]) >= 应差 * 0.6, len(店),
           f"实际跨度 {分[-1]-分[0]:.2f} —— **三家店一样的话,铁律说的「门店之间可以比」"
           f"在数据上没有对象**")
    # ── 趋势:**按店配对后合并**,每店单独只判方向 ────────────────────────
    # ⚠️ 这条判据改过三版,每一版都是被数据打回来的:
    #   ① 判「全店整体月均」→ 本地 +0.29、**CI 从零重建只有 +0.08**。
    #      根因:每月门店构成不同(9 月杭州店占比高,整体月均被拉低)。
    #   ② 改判「每店自己 7月→9月」→ 一度仍然挂。查下来是**两件事叠在一起**:
    #      · 造数按「签收月」挑目标、检查按「评价月」分组 —— **两处口径不一致**,
    #        表现成 7 月系统性偏高、9 月系统性偏低(已修,在 backfill_rating 里);
    #      · **每店每月只有 40~100 条**,两端之差的标准误 0.13~0.23,
    #        而阈值是 0.15 —— **判据比噪声还紧,第三次踩同一个形状**。
    #   ③ 现在:**按店配对后合并**当主判据(去掉了构成影响,样本量又够),
    #      每店单独**只判方向**(容忍到 -0.10),实际值照实报。
    #
    # > 「每家店自己在涨」是业务的说法,也是铁律 TK13 认的比法;
    # > 但**一家店一个月几十条评价,判不出 0.3 的升幅** —— 合并才判得出。
    店月 = {(r["shop"], r["ym"]): (r["n"], r["a"]) for r in c.execute(
        """SELECT o.shop, substr(r.rated_at,1,7) ym, COUNT(*) n, AVG(r.star) a
             FROM rating r JOIN ordr o ON o.id=r.order_id GROUP BY 1,2""")}
    # 月份按**造数那天**的世界日期现算(造数和检查同一个口径);
    # 「造数之后世界没再平移过」由下面 rating_built_on 那条守着。没记就退回今天。
    import datetime as _dt
    _建 = c.execute("SELECT v FROM world_meta WHERE k='rating_built_on'").fetchone() \
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='world_meta'").fetchone() else None
    月目标 = SR.月目标_于(_dt.date.fromisoformat(_建[0]) if _建 else worldclock.今天())
    有的 = sorted(月目标)
    if len(有的) >= 2:
        头, 尾 = 有的[0], 有的[-1]
        应升 = 月目标[尾] - 月目标[头]
        差们 = []
        for shop in sorted(SR.门店均分):
            a, b = 店月.get((shop, 头)), 店月.get((shop, 尾))
            if not (a and b):
                ck(f"{shop} 在 {头} / {尾} 都有评价", False, 0,
                   "缺月份,趋势判不了 —— **判不了不算通过**"); continue
            差们.append((shop, b[1] - a[1], a[0] + b[0], a[1], b[1]))
            # 每店单独**只判方向**:样本小,判不了幅度
            ck(f"{shop} 自己没有下滑(每月只 {min(a[0], b[0])} 条,**判不了幅度,只判方向**)",
               (b[1] - a[1]) >= -0.10, a[0] + b[0],
               f"{a[1]:.2f} → {b[1]:.2f}({b[1]-a[1]:+.2f})")
        if 差们:
            W = sum(x[2] for x in 差们)
            合 = sum(x[1] * x[2] for x in 差们) / W
            ck(f"**按店配对合并后**从 {头} 到 {尾} 在上升"
               f"(业务拍的升 {应升:.2f},至少要有它的一半)",
               合 >= 应升 * 0.5, W,
               f"合并升 {合:+.2f}(" + " · ".join(f"{s.split()[-1]} {d:+.2f}" for s, d, *_ in 差们)
               + ")—— **配对去掉了门店构成的影响,合并又把样本量凑够了**")
        全 = {r["ym"]: r["a"] for r in c.execute(
            """SELECT substr(rated_at,1,7) ym, AVG(star) a FROM rating GROUP BY ym""")}
        print("     ℹ 全店整体月均(**报而不判**,它被门店构成搅乱 —— 造数自测里真出现过"
              "每家店都涨、整体反而跌):"
              + " → ".join(f"{m} {全[m]:.2f}" for m in 有的 if m in 全))
    ck("差评占比在一成上下(业务知情:当面难给差评,所以分数偏高)",
       0.03 <= (lambda x: x)(c.execute(
           "SELECT 1.0*SUM(star<=?)/COUNT(*) FROM rating", (R.差评线,)).fetchone()[0]) <= 0.25,
       n, f"实际 {c.execute('SELECT 1.0*SUM(star<=?)/COUNT(*) FROM rating',(R.差评线,)).fetchone()[0]:.1%}")


def 合成夹具自证():
    """造几行故意坏掉的数据,确认每条判据**真的会红**。

    ⚠️ 这不是「多测一遍」。真库上这张表是空的(业务:造数先别铺)——
    **空表上跑判据,等于判据从来没被执行过**,而那和「查过了没问题」在输出上一模一样。
    """
    import seed_rating
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.executescript("""
      CREATE TABLE pickup_item(order_item_id INTEGER PRIMARY KEY, pkg_id TEXT,
                               fit_result TEXT, fit_at TEXT);
      CREATE TABLE pkg_item(item_id INTEGER PRIMARY KEY, pkg_id TEXT);
      CREATE TABLE task(id TEXT PRIMARY KEY, type TEXT, ref_id TEXT, status TEXT,
                        created TEXT, summary TEXT);
    """)
    seed_rating.建表(c)
    好 = R.来源_顾客 if hasattr(R, "来源_顾客") else "顾客小程序"
    def 签(pkg, at="2026-09-20 15:00"):
        c.execute("INSERT INTO pickup_item VALUES(?,?,'合身',?)", (abs(hash(pkg)) % 10**8, pkg, at))
    def 评(pkg, **kw):
        d = dict(pkg_id=pkg, order_id="O1", customer_id=1, star=5, note="x",
                 rated_at="2026-09-20 16:00", src=好, advisor_no="S1", edit_cnt=0,
                 edited_at=None, star_before=None, task_id=None,
                 handled_at=None, handled_by=None, handle_note=None)
        d.update(kw)
        c.execute(f"INSERT INTO rating({','.join(d)}) VALUES({','.join('?'*len(d))})", tuple(d.values()))
    def 工单(tid, pkg, status="待处理"):
        c.execute("INSERT INTO task VALUES(?,?,?,?,?,?)", (tid, 工单类型, pkg, status, "t", "s"))

    # 每个判据配一行坏数据,**一行只坏一件事** —— 一行坏两件,分不清红的是哪一条
    签("PA"); 评("PA")                                            # 干净的对照
    评("PB")                                                      # 没签收就评了
    签("PC"); 评("PC", star=9)                                    # 星级不合法
    签("PD"); 评("PD", star=2)                                    # 差评没进清单
    签("PE"); 工单("TRPE", "PE"); 评("PE", star=5, task_id="TRPE")  # 好评却挂了工单
    工单("TRPF", "PF")                                            # 工单没有对应的评价
    签("PG"); 工单("TRPG", "PG", "已关闭"); 评("PG", star=2, task_id="TRPG")  # 关了没写记录
    签("PH"); 工单("TRPH", "PH"); 评("PH", star=2, task_id="TRPH",
                                    handled_at="2026-09-21 10:00")  # 两处状态打架
    签("PI"); 评("PI", src="导购端")                                # 来源不对
    签("PJ"); 评("PJ", edit_cnt=1)                                 # 改过却没留痕
    签("PK"); 评("PK", star=2, note=SR.好评评语[0])                 # 差评挂了好评评语
    # ⚠️ **两个方向各一行。** 第一版只有 PK(差评挂好评语),于是
    # 「只查一个方向」那个攻击**改坏了却没红** —— 夹具里没有反向那一行,攻击没有对象。
    签("PL"); 评("PL", star=5,
               note=sorted(SR.差评评语)[0] and SR.差评评语[sorted(SR.差评评语)[0]][0])  # 好评挂差评语
    c.commit()

    print("\n  合成夹具自证:每条判据**真的会红,而且红的是指定那一行**")
    print("    (判据写成函数,和真库跑的是同一份;夹具里一行只坏一件事)")
    没红 = []
    for 名, f in 判据:
        坏 = f(c)
        想抓 = 该抓谁[名]
        中 = [x for x in 坏 if 想抓 in str(tuple(dict(x).values()))]
        ok = bool(中)
        if ok:
            print(f"    ✅ {名} —— 抓到了 {想抓}" + (f"(另外还抓到 {len(坏)-len(中)} 条)" if len(坏) > len(中) else ""))
        else:
            print(f"    ❌ {名} —— **没抓到 {想抓}**" +
                  (f",抓到的是 {[dict(x) for x in 坏][:2]} —— **红的不是那一条**"
                   if 坏 else ",一条都没抓到,这条判据没在干活"))
            没红.append(名)
    # ⚠️ **「抓到了」不等于「抓对了」。** 第一版这里只判 `bool(坏)`,
    # 于是咬合当场抓到:把「两处状态打架」的判据改成查别的条件,它照样抓到夹具里另一行 ——
    # **改坏了却没红**。这和咬合第三关问的是同一件事:红的是不是那一条。
    # 对照那一行不许被任何判据抓到 —— **判据别开大了**
    脏 = [名 for 名, f in 判据 if any(dict(x).get("pkg_id") == "PA" for x in f(c))]
    print(f"    {'✅' if not 脏 else '❌'} 干净的那一行没被任何判据冤枉"
          + (f" —— 被 {脏} 抓了" if 脏 else ""))
    if 脏: 没红 += [f"判据开大了:{脏}"]
    return 没红


def main():
    print("评价数据 · 检查")
    print("=" * 92)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    有表 = c.execute("SELECT 1 FROM sqlite_master WHERE name='rating'").fetchone()
    ck("库里有评价表(ensure_tables 跑过)", bool(有表), 1)
    if not 有表:
        print("\n\033[31m❌ 表都没有,后面的一条都没验\033[0m"); sys.exit(1)
    # ── 造数之后世界没有再被平移过 ────────────────────────────────────
    # ⚠️ 这一条防的是**步骤顺序**,而顺序是最容易被挪回去的东西。
    # 2026-09-27 CI 连红两次:`backfill_rating.py` 在 rebuild 里排在 `shift_world` 之前,
    # 于是它按「平移前的月」给目标(世界当时停在建库基准日 2026-08-31),
    # 而平移 +27 天把那批评价挪成了 9 月 —— **月份标签变了,目标没变**。
    # 业务拍的「三个月上升」被抹掉大半(设计 0.30,实现只剩 0.10~0.18)。
    # 「签收月 vs 评价月」那个错的第三个位置:前两次在一个文件里,这次藏在顺序里。
    建于 = (c.execute("SELECT v FROM world_meta WHERE k='rating_built_on'").fetchone()
           or [None])[0]
    现在 = str(worldclock.今天())
    ck("造数之后世界没有再被平移过(月份标签还是造数时那些)", 建于 == 现在, 1,
       f"造数时世界停在 {建于},现在是 {现在} —— "
       f"**`tools/backfill_rating.py` 必须排在 `tools/shift_world.py` 之后**"
       if 建于 != 现在 else f"两边都是 {现在}")

    n = 查一遍(c)
    if n == 0:
        print("\n  \033[33mℹ 评价表现在是空的(业务 2026-09-27:造数先别铺)—— "
              "**上面那几条一条数据都没扫到**。\033[0m")
        print("    「没扫到东西」不是「都通过」。判据有没有在干活,靠下面那半证明。")
    if n:
        查形状(c, n)
    没红 = 合成夹具自证()
    FAIL.extend(没红)
    print("=" * 92)
    if FAIL:
        print(f"\033[31m❌ 评价数据 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 评价数据 {N[0]} 条不变量 + {len(判据)} 条判据自证全过"
          f"(真库 {n} 条评价)\033[0m")


咬合 = [
    # ⚠️ 这两条的**攻击对象在 `tools/backfill_rating.py --selftest` 上**,不在这儿:
    # 咬合**不会重新造数**,改造数脚本的常量打不到真库上这份检查;
    # 而且改 `门店均分` 会**同时改掉这份检查的期望值**(它就是从那儿读的)。
    # 规格见 bite_specs.json 里 script 为 `tools/backfill_rating.py --selftest` 的那几条。
    ("(形状那几条的咬合挂在 backfill_rating 的自测上)", "门店之间真的拉开了差距"),
    ("让 评语和星级对不上() 只查一个方向", "评语和星级对不上"),
    # ⚠️ 「造数之后世界没有再被平移过」这一条**没有可重放的文件级咬合** ——
    # 咬合**不重新造数**,改造数脚本改不了库里那个 `rating_built_on`;
    # 而它守的是 **rebuild 的步骤顺序**,那要真跑一次重建才动得了。
    # 它是怎么被验的,写在这儿(**比一条假咬合有用**):
    #   · **真实事故验过**:CI 连红两次(合并升 +0.10 / +0.175,而设计是 0.30),
    #     根因正是 backfill_rating 排在 shift_world 之前;
    #   · **改顺序之后从零重建**,同一条判据 +0.27,回到设计值附近;
    #   · 它依赖的那个机制(造数记下自己用的世界日期)**有咬合**,
    #     在 `tools/backfill_rating.py --selftest` 上(「记下了造数时的世界日期」)。
    ("(顺序那条:文件级咬合打不到,见上面注释里它是怎么验的)",
     "造数之后世界没有再被平移过"),
    ("让 没签收就评了() 只查签收于 IS NULL(不比先后)", "没签收就评了"),
    ("让 差评没进清单() 把 star<= 改成 star<(3 星就漏了)", "差评没进清单"),
    ("让 两处状态打架() 只看 task.status,不看 rating.handled_at(它会抓到别的行)", "两处状态打架"),
    ("让 好评却挂了工单() 直接返回空(反向那一半不查了)", "好评却挂了工单"),
    ("把合成夹具里那行干净数据改成 star=9", "干净的那一行没被任何判据冤枉"),
]

if __name__ == "__main__":
    main()
