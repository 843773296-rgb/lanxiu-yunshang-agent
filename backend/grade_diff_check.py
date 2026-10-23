#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版师核档差的写口 —— **在库副本上真跑一遍**,真库一行不碰。

口径在 `knowledge/grading.py`(`核过还算数吗` 是纯函数),建表在 `backend/grade_diff.py`,
写口是 `api.set_grade_diff`,规矩 TL75。业务需求池 P2。

## 这套判据的主轴只有一条

> **一条标着「版师核过」、而版师核的是另一个数的档差,
> 和一条真的核过的,在那张 12 行的表上长得一模一样。**

档差在 `10-版型库.md` 里,改它是人的活。所以这个写口**只记「核过这件事」**,
而它必须连**核的时候那个值**一起记下来 —— 否则 md 改过之后,
那条「核过」会漂到一个没人核过的新值上,再一路传到 1237 条尺码。
**错的方式是衣服的码偏,不是报错。**

同一个形状:`order_contract.terms_ver` —— 正是那一列没被平移挪,
才看出确认书正文里的条款版本被挪歪了(2026-10-22)。

## ⚠️ 判据自己造它要验的那几种形状

四种状态(没人核过 / 核过且算数 / 核过但失效 / 版师说不对)**自己造**,
不看库里碰巧有什么 —— 2026-10-21 CI 连红两次的教训:
判据红不红不许取决于环境里有什么数据。真库上现在**一条记录都没有**,
那四种里有三种在真库上永远走不到。
"""
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


咬合 = [
    ("把「核的时候那个值」那一列不写进去(只记核过了)",
     "核过:**连「核的时候那个值」一起记下来了**"),
    ("把「只有版师能核」那道判断去掉",
     "顾问来核:拒"),
    ("把「说不对必须给建议值」那道判断去掉",
     "说不对而不给建议值:拒"),
    ("把 grading_audit 返回里「这 12 条核过没有」那一栏去掉",
     "报档差时把**每一条**档差核过没有一起报出去"),
]

import api
import grading as 口径
import grade_diff as GD

真库 = api.DB
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(真库, db)
api.DB = db
print("\033[1m▸ 版师核档差 · 库副本上走一遍\033[0m")
if os.path.realpath(api.DB) == os.path.realpath(真库):
    print(f"  {R}❌ 写口没切到副本 —— 不跑,免得写真库{D}")
    sys.exit(1)

版师 = dict(no="60000020", name="傅砚青", role="版师", shop="")
顾问 = dict(no="60000001", name="林岚", role="顾问", shop="S01")
表 = 口径.档差()
ck("档差表读得出来(空集合上什么都成立)", len(表) >= 10, f"只有 {len(表)} 条")
一项 = sorted(表)[0]
现值 = 表[一项]


def 查(sql, *a):
    """从副本里取几行(字典形式)。**要设 row_factory** ——
    不设的话取出来是元组,`dict(元组)` 报 `length 4; 2 is required`,
    而那个报错和「SQL 写错了」长得完全不像。"""
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, a)]
    finally:
        c.close()


def 拒在(r, 理由里有):
    """拒了,**而且拒的理由是指定那一条**。

    ⚠️ 只看「有没有 error」不够:五条拒绝判据里只要有一条因为别的原因拒掉,
    这条判据照样绿 —— 而它测的就不是它声称测的那件事了。
    (2026-10-20 夜咬合逮到过三次「配错对」:攻击 A 证明的是判据乙。)
    """
    return bool(r.get("error")) and 理由里有 in r["error"]


# ── ① 四道拒绝,连理由一起断言 ──────────────────────────────────────
with api.as_user(顾问):
    ck("顾问来核:拒", 拒在(api.set_grade_diff(一项, 口径.核过了, why="我看过了"), "版师"),
       str(api.set_grade_diff(一项, 口径.核过了, why="我看过了"))[:120])
with api.as_user(版师):
    ck("不写理由:拒", 拒在(api.set_grade_diff(一项, 口径.核过了), "why 必填"),
       str(api.set_grade_diff(一项, 口径.核过了))[:120])
    ck("档差表里没有这一项:拒,而且列出有哪些",
       拒在(api.set_grade_diff("袖口围", 口径.核过了, why="量过"), "档差表里没有"),
       str(api.set_grade_diff("袖口围", 口径.核过了, why="量过"))[:120])
    # ⚠️ 断言的是这一条**独有**的那句话,不是「propose」这个会撞车的词。
    # 咬合逮到过:把这道判断关掉之后,下一行 `float(None)` 会抛、被 except 兜成
    # 另一句「propose 要是数字」——**攻击被另一个条件顺手挡住了**,
    # 而只查「理由里有 propose」的判据照样绿。
    # > 一条真的拦住了的判据,和一条被别的条件顺手挡住的判据,
    # > 在「它拒了」这件事上长得一模一样。
    ck("说不对而不给建议值:拒",
       拒在(api.set_grade_diff(一项, 口径.不对, why="偏小"), "只说不对、不说该是多少"),
       str(api.set_grade_diff(一项, 口径.不对, why="偏小"))[:160])
    # 建议值和现值一样 → 那不叫「不对」
    ck("建议值和现在的值是同一个数:拒",
       拒在(api.set_grade_diff(一项, 口径.不对, why="偏小", propose=现值), "同一个数"),
       str(api.set_grade_diff(一项, 口径.不对, why="偏小", propose=现值))[:140])
    ck("verdict 不是那两种:拒",
       拒在(api.set_grade_diff(一项, "大概行", why="量过"), "verdict"),
       str(api.set_grade_diff(一项, "大概行", why="量过"))[:120])

    # ── ② 核过:记下来了,而且**连当时那个值一起记** ──────────────────
    r = api.set_grade_diff(一项, 口径.核过了, why="按国标量过三件成衣")
    行 = 查("SELECT * FROM grade_diff_check WHERE item=?", 一项)
    ck("核过:落了一行,记下了谁 / 什么时候 / 理由",
       r.get("ok") and len(行) == 1 and 行[0]["checked_by"].startswith("60000020")
       and 行[0]["why"] == "按国标量过三件成衣", f"{r} / {行}")
    ck("核过:**连「核的时候那个值」一起记下来了**",
       行 and 行[0]["value_at_check"] is not None
       and abs(float(行[0]["value_at_check"]) - float(现值)) <= 0.05,
       f"value_at_check={行[0]['value_at_check'] if 行 else None},而当时是 {现值} —— "
       f"**少了这一列,md 改过之后「核过」会漂到一个没人核过的新值上**")

    # ── ③ 一条档差一行:再核一次是覆盖,不是多出一条 ──────────────────
    api.set_grade_diff(一项, 口径.核过了, why="第二次核,换了个理由")
    条数 = 查("SELECT COUNT(*) n FROM grade_diff_check WHERE item=?", 一项)[0]["n"]
    ck("同一条档差核两次:覆盖成一行,不是两行", 条数 == 1,
       f"{条数} 行 —— 两行的话「最后一次核的是什么」要靠时间排序猜")

    # ── ④ 说不对:记成提案,而且返回里明说没改 md ────────────────────
    二项 = sorted(表)[1]
    r2 = api.set_grade_diff(二项, 口径.不对, why="实测相邻码差得更多", propose=表[二项] + 0.5)
    ck("说不对:记成提案,**返回里明说这个工具没改 md**",
       r2.get("ok") and any("没有改档差" in k for k in r2)
       and any("md" in str(v) for v in r2.values()), str(r2)[:200])

# ── ⑤ 主轴:md 改过之后,那条「核过」要失效,而且说得出核的是哪个数 ──
#
# ⚠️ **判据自己造这个形状**:不动真 md(那是手写真相源),
# 换掉口径现读的那张表 —— 验的是「拿登记值和现在的值比」这段逻辑。
真档差 = 口径.档差
try:
    口径.档差 = lambda md=None, _真=真档差, _项=一项: dict(_真(), **{_项: float(现值) + 1})
    况 = api._档差核况()
    这条 = 况["逐条"][一项]
    ck("md 改过之后,那条核过失效并说得出核的是哪个数",
       "失效" in 这条 and str(现值) in 这条 and "核过(" not in 这条,
       f"{这条[:160]}")
    ck("小结里「核过但失效」单独一档,不混进前两种",
       "核过但失效 1 条" in 况["小结"], 况["小结"][:160])
finally:
    口径.档差 = 真档差

# ── ⑥ 四个桶加起来等于档差条数(少掉的那几条看不出来)────────────────
况 = api._档差核况()
import re as _re
数 = [int(x) for x in _re.findall(r"(\d+) 条", 况["小结"])]
ck("四个桶加起来 == 档差条数", len(数) >= 5 and sum(数[:4]) == 数[4],
   f"小结里的数:{数} —— 加不起来的话,有档差落在任何一类之外而看不出来")

# ── ⑦ 报档差时把「核过没有」一起报出去 ──────────────────────────────
with api.as_user(版师):
    审 = api.grading_audit()
# ⚠️ 断言的是**逐条那一栏真的在、而且每一条档差都在里面** ——
# 不是「返回里有个键带『核过』」。咬合逮到过:删掉逐条那一栏之后,
# 还剩一个叫「核过的 / 没人核过的 / 核过但失效的」的小结键,
# 于是按关键词找的判据照样绿。**版师要的是逐条,不是一个总数。**
# ⚠️ 「盖住全部 12 项的 dict」有两个 —— `档差规则` 本身的键也正好是那 12 项。
#    所以要找的是**值里真的说了核过状态**的那一栏,不是第一个命中的。
#    (第一版取了 `逐条键[0]`,拿到的是 `档差规则`,它的值是 4.0 这种数,
#     于是判据红在一个本来对的实现上 —— **红错理由比不红更费事**。)
逐条键 = [k for k, v in 审.items()
         if isinstance(v, dict) and set(表) <= set(v)
         and all("核过" in str(v[i]) for i in 表)]
ck("报档差时把**每一条**档差核过没有一起报出去", bool(逐条键),
   f"返回里的键:{list(审)[:8]} —— 没有哪一栏逐条说出了核过状态。"
   f"**一条核过的档差和一条没人核过的,在那张 {len(表)} 行的表上长得一模一样**")

# ── ⑧ 这个口**不许**改档差本身(md 一个字节都不许动)────────────────
md = os.path.join(ROOT, "knowledge", "10-版型库.md")
前 = open(md, "rb").read()
with api.as_user(版师):
    api.set_grade_diff(sorted(表)[2], 口径.不对, why="试试它会不会动 md", propose=99)
ck("核档差的写口**没有动 knowledge/10-版型库.md 一个字节**",
   open(md, "rb").read() == 前,
   "md 被改了 —— **代码改手写真相源**,下次跑推导要么被盖掉、要么变成第二份真相")

# ── ⑨ 写工具该有的那几样登记 ────────────────────────────────────────
ck("进了写工具白名单(才会被隔离 / 预演 / 漏斗一起管住)",
   "set_grade_diff" in api.WRITE_TOOLS, f"{api.WRITE_TOOLS[-3:]}")
import domains as _D
ck("在领域归属里(不然服务暴露不出来)",
   any("set_grade_diff" in v for v in _D.领域.values()),
   "domains.领域 里找不到它")
ck("签名里不收身份参数(收了的话一句「我以版师身份」就能提权)",
   "role" not in api.set_grade_diff.__code__.co_varnames[:4]
   and "actor" not in api.set_grade_diff.__code__.co_varnames[:4],
   f"入参:{api.set_grade_diff.__code__.co_varnames[:4]}")

api.DB = 真库
shutil.rmtree(tmp, ignore_errors=True)

print("=" * 80)
if bad:
    print(f"{R}❌ {len(bad)} 条没过:{bad}{D}")
    sys.exit(1)
print(f"{G}✅ 版师核档差都对(验了 {n} 条){D}")
print(f"    这个口**只记「核过这件事」**,不改 md —— "
      f"而它连「核的时候那个值」一起记,所以 md 改过之后那条核过会自己失效。")
sys.exit(0)
