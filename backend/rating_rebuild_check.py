#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**差评造数的产物,和库里那批,必须是同一批。**

    python3 backend/rating_rebuild_check.py

在**库副本**上清空 `rating`、用现在的代码重跑一遍 `tools/backfill_rating.py`,
拿它造出来的那批和库里现在那批逐条比。共享库一个字都不动。

## 它守的是哪件事(2026-10-13 一整天的 CI 红换来的)

> **「改了造数脚本」和「库跟着重跑了」是两件事,
> 而本机永远看不出区别** —— 因为本机从不重建。

那天的样子:CI 连红 7 次,红的是题集判据「三套并起来 ≠ 库里人工处置过的那批」。
查出来是 `tools/backfill_rating.py` 被改过(10-12 拍掉「优惠券」那笔),
而共享库里那批是**改之前**的代码造的 —— 实测只重合 16/158 条。
CI 每次从零建库、用的是现在的代码,所以**只有它撞得上**。

而更值得记的是当时那两个候选解释:

    ① 造数用「今天」算差评多老 → 从零重建每天产出不同
    ② 库里那批是旧代码造的

**它们在 CI 那条红上长得一模一样。** 我先写了 ①(还写进了判据注释、
摆给用户让他拍了方案),**最后才去验** —— 一验是 ②。
分开它们靠的就是这支检查做的事:在副本上重跑一遍,比一比。

## 为什么不是「记下造数时的世界日期」那条守卫

`tools/backfill_rating.py` 第 440 行附近记着 `rating_built_on`,
由 `backend/rating_check.py` 断言它和现在的世界日期一致。
那条**守的是另一件事**(造完数之后世界有没有再被平移过),而且它那天是绿的 ——
因为配方里先平移再造数,两个日期当然一致。

> **一条守「库内部一致」的断言,和一条守「产物和代码一致」的断言,
> 在那个绿勾上长得一模一样。**

## 这条检查慢(要真跑一遍造数),而它仍然进门禁

`check.sh` 里跑一遍约一分钟。**不进门禁等于不存在** ——
这个项目 2026-10-03 发现过三份自测从写好那天起没进过门禁,而门禁一直绿。
"""
import io, json, os, shutil, sqlite3, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "knowledge"), HERE, ROOT]

# ── 咬合记录 ──────────────────────────────────────────────────────────
#
# ⚠️ 这份清单和 `tools/bite_specs.json` 里那两条规格**是两件事**:
# 那边是**真跑**的(在工作区副本上重放:对照绿 → 改坏 → 红的是点名那一条),
# 这边是**登记**给人读的。两份都要有 —— 2026-10-13 我只加了那边,
# 门禁里那条棘轮(「没有咬合记录的脚本不超过 0 个」)当场红了。
# > **「我做了咬合」和「这个脚本登记了它做过咬合」是两件事。**
咬合 = [
    ("把造数里不出钱那一族的配对列表删掉一项(改了造数脚本,而库里那批是改之前造的)",
     "**重跑造出的那批号,和库里那批一模一样**"),
    ("往处理方式枚举里加一档而造数里没有它(枚举多一个值,数据里零样本)",
     "枚举里每一档在库里都有样本"),
]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0
DB = os.path.join(HERE, "lanxiu.db")


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


def 取(dbp):
    """(包裹号 → 处理方式) 的全集。**只取已处置的** —— 没处置的那批没有真值。"""
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    out = {r[0]: r[1] for r in c.execute(
        "SELECT pkg_id, handle_way FROM rating "
        "WHERE handle_way IS NOT NULL AND handle_way<>''")}
    c.close()
    return out


print("差评造数的产物和库里那批是不是同一批(**在库副本上真重跑一遍**)")

库 = 取(DB)
ck(f"样本量:库里已处置 {len(库)} 条(0 条的话下面全是空集合上的真)",
   len(库) >= 50, f"只有 {len(库)} 条")

副目 = tempfile.mkdtemp(prefix="ratingrebuild-")
副本 = os.path.join(副目, "lanxiu.db")
shutil.copy(DB, 副本)
c = sqlite3.connect(副本)
c.execute("DELETE FROM rating")
c.commit()
c.close()

t0 = time.time()
import backfill_rating as B
说 = []
rc = B.铺(db=副本, 说=说.append)
用时 = time.time() - t0
ck(f"重跑跑得通(退出码 0,用了 {用时:.0f} 秒)", rc == 0, f"退出码 {rc};{说[:2]}")

新 = 取(副本)
ck(f"重跑也造出了样本({len(新)} 条)—— 为 0 时下面那条等于没验", len(新) >= 50,
   f"只有 {len(新)} 条")

# ── 要害那一条 ────────────────────────────────────────────────────────
同号 = set(库) == set(新)
ck("**重跑造出的那批号,和库里那批一模一样**", 同号,
   f"重合 {len(set(库) & set(新))} / 库里独有 {len(set(库) - set(新))}"
   f"(例 {sorted(set(库) - set(新))[:2]}) / 重跑独有 {len(set(新) - set(库))}"
   f"(例 {sorted(set(新) - set(库))[:2]}) —— "
   f"**造数脚本改过而共享库没重跑**(或反过来)。"
   f"修法:`python3 -c \"import sqlite3;c=sqlite3.connect('backend/lanxiu.db');"
   f"c.execute('delete from rating');c.commit()\"` 然后 "
   f"`python3 tools/backfill_rating.py`,**而那等于换考卷** —— "
   f"题集的真值就是这些档位,改完要 `python3 agent/triage_sets.py --冻`,"
   f"并在提交信息里说为什么")

# 号对得上之后再比档位 —— 号都不一样的话,比档位只会刷出一堆噪音
if 同号:
    漂 = [(k, 库[k], 新[k]) for k in sorted(库) if 库[k] != 新[k]]
    ck("每一条的处理方式也一模一样", not 漂,
       f"{len(漂)} 条的档位不同,例 {漂[:2]} —— 号对得上而档位漂了,"
       f"说明有人**改过库里的处置**(走写口改的也算),或者造数的发档逻辑改了")

# ── 枚举里每一档都有样本 ──────────────────────────────────────────────
#
# ⚠️ 这一条是 2026-10-13 加「免运费」那天逼出来的:枚举里多一个值而数据里零样本,
# 等于那一档的写口、页面、判据**全都验不到** ——「空集合上所有性质都成立」。
import rating as RT
有样本 = {}
for v in 库.values():
    有样本[v] = 有样本.get(v, 0) + 1
for m in RT.处理方式:
    print(f"    {m}:{有样本.get(m, 0)} 条")
零 = [m for m in RT.处理方式 if not 有样本.get(m)]
ck("枚举里每一档在库里都有样本(零样本那一档,它的写口和判据全都验不到)",
   not 零, f"这几档零样本:{零} —— 要么把它造进 `tools/backfill_rating.py` "
   f"的配对列表,要么它根本不该在枚举里")
枚举外 = sorted(set(库.values()) - set(RT.处理方式))
ck("库里没有枚举外的档(写口只认枚举,枚举外的档是绕过写口写进来的)",
   not 枚举外, f"枚举外:{枚举外}")

shutil.rmtree(副目, ignore_errors=True)

print(f"\n📌 这条检查**不验**造数造得对不对(形状、分布、趋势那些由 "
      f"`backend/rating_check.py` 管);它只验**库里那批和现在的代码对得上**。")
if bad:
    print(f"\n{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    for b in bad:
        print(f"   · {b}")
    sys.exit(1)
print(f"\n{G}✅ 库里那批差评就是现在这份代码造出来的(验了 {n} 条){D}")
