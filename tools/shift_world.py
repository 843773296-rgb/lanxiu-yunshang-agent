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

# 这套数据当初照哪一天写的 —— 库里还没有 meta 时按它算
基准 = "2026-08-31"

# 整列日期的判据。**要容得下 `2026-02-16 9:16` 这种单位数小时** ——
# 第一版写的是 `\d{2}:\d{2}`,于是 edit_log.ts(542 条)被判成「文字列」漏掉了,
# 而它是一个不折不扣的时间戳列。**格式写严一点点,就会把一整张表留在过去。**
整列日期 = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")
任一日期 = re.compile(r"\d{4}-\d{2}-\d{2}")

# ── 登记:文字里埋着日期的列,挪还是不挪 ────────────────────────────
文字里也挪 = {
    "factory_msg.reason": "「工厂接单,承诺 2026-09-24 完工」复述的就是同一行的 promise_date —— "
                          "不挪的话,同一条记录里结构化字段和它自己的说明**互相矛盾**",
    "op_log.reason": "派工记录里写着上门时间(「2026-10-04 14:00 → 16:00」),"
                     "它复述的是 task 上的时间",
    "order_mix_batch.payload": "订单快照的 JSON,里面是那一单当时的各个时间点",
}
文字里不挪 = {
    "color_family.note": "「(业务 2026-09-20 定)」是**来路** —— 记的是人哪天拍的板,"
                         "不是世界里发生的事。世界挪了,人拍板那天没挪",
    "truth.expected_evidence": "同上,标注答案里写着依据是哪天定的;"
                               "而且这是标注答案表,内容本身就不该跟着数据动",
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
    if 天 and db == DB:
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
def 查(db=DB, 说=print):
    """三件事:库说自己停在哪天、数据实际停在哪天、离真实今天差几天。

    **前两件对不上就是红的** —— 那说明有一列日期没跟着挪(或者有人手改了库),
    而它的表现是「某张表停在过去」,不会报错。
    第三件是**提醒不是错**:几天没平移不是代码坏了,是该跑一下了;
    但差太久就当红的算 —— 那时候「下周没有单」这种假空又会回来。
    """
    坏 = []
    if not os.path.exists(db):
        说("  ⚠ 还没有库(没重建过)—— 跳过"); return []
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
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
    if 差 > 14:
        坏.append(f"数据停在 {说自己},离今天 {差} 天 —— 太久了,"
                  f"「下周一条单都没有」这种假空会回来。跑:python3 tools/shift_world.py")
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

    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(_自测())
    if "--check" in sys.argv:
        print("演示世界的日期 · 自洽检查\n" + "=" * 76)
        坏 = 查()
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
    标记 = os.path.join(os.path.dirname(DB), ".shifting")
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

    print(f"把演示世界平移到 {到}")
    print("=" * 76)
    r = 平移(到=到)
    if r.get("错"):
        print(f"\033[31m❌ {r['错']}\033[0m")
        print("   新加的表/列里有日期就要在 tools/shift_world.py 里登记:"
              "复述结构化日期的跟着挪,记「业务哪天定的」的不挪")
        sys.exit(1)
    print(f"\033[32m✅ 世界现在停在 {r['到']}\033[0m")
