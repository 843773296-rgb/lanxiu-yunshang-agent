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
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import rating as R

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
         "来源不对": "PI", "改过却没留痕": "PJ"}

判据 = [("没签收就评了", 没签收就评了), ("星级不合法", 星级不合法),
       ("差评没进清单", 差评没进清单), ("好评却挂了工单", 好评却挂了工单),
       ("工单没有对应的评价", 工单没有对应的评价),
       ("关了却没写处理记录", 关了却没写处理记录),
       ("两处状态打架", 两处状态打架), ("来源不对", 来源不对),
       ("改过却没留痕", 改过却没留痕)]


def 查一遍(c, 前缀=""):
    n = c.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
    for 名, f in 判据:
        坏 = f(c)
        ck(f"{前缀}{名} —— 一条都没有", not 坏, n, (f"{len(坏)} 条:{坏[:2]}" if 坏 else ""))
    return n


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
    n = 查一遍(c)
    if n == 0:
        print("\n  \033[33mℹ 评价表现在是空的(业务 2026-09-27:造数先别铺)—— "
              "**上面那几条一条数据都没扫到**。\033[0m")
        print("    「没扫到东西」不是「都通过」。判据有没有在干活,靠下面那半证明。")
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
    ("让 没签收就评了() 只查签收于 IS NULL(不比先后)", "没签收就评了"),
    ("让 差评没进清单() 把 star<= 改成 star<(3 星就漏了)", "差评没进清单"),
    ("让 两处状态打架() 只看 task.status,不看 rating.handled_at(它会抓到别的行)", "两处状态打架"),
    ("让 好评却挂了工单() 直接返回空(反向那一半不查了)", "好评却挂了工单"),
    ("把合成夹具里那行干净数据改成 star=9", "干净的那一行没被任何判据冤枉"),
]

if __name__ == "__main__":
    main()
