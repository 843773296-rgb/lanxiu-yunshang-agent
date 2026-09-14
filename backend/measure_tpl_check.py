#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量体模版管理的检查 —— **改一个被引用的模版是这块最危险的动作。**

## 危险在哪

模版被 N 个商品挂着、被 M 条量体记录用过。
从模版里**移掉一个测量项**,那些历史记录就指向一个模版已经不包含的项。

**既不算错也不算对,而且没有任何检查会报** —— 它不违反任何外键。
报表上完全正常:记录还在、模版还在、商品还在,只是它们不再自洽。

所以这块的重点**不是让它能改**,是**改之前先说清影响面、不可逆的动作先挡住**:

    移一项   不可逆(历史记录会悬空)  → 已经量过的那一项**不许移**
    停用     可逆                    → 想临时停掉走这条
    删模版   不可逆                  → 被引用就不许删,而且要说清被谁引用

> 「删不了」这三个字没用 —— 看的人还要自己去翻是哪几个商品挂着它。
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(HERE, "lanxiu.db"), os.path.join(tmp, "lanxiu.db"))
    import server
    server.DB = os.path.join(tmp, "lanxiu.db")
    server.ensure_editlog()
    c = sqlite3.connect(server.DB)

    被引用 = [r[0] for r in c.execute(
        "SELECT t.code FROM measure_tpl t WHERE EXISTS"
        "(SELECT 1 FROM measure_rec m WHERE m.tpl=t.code)")]
    ck("有被引用的模版可以拿来试", bool(被引用), len(被引用),
       "没有的话下面几条都是空跑 —— **空跑不叫通过**")
    if not 被引用:
        print("=" * 84); return 1
    tc = 被引用[0]
    旧项 = [r[0] for r in c.execute(
        "SELECT item FROM tpl_item WHERE tpl=? ORDER BY sort", (tc,))]
    量过 = [r[0] for r in c.execute(
        "SELECT DISTINCT item FROM measure_rec WHERE tpl=?", (tc,))]
    留 = [i for i in 旧项 if i not in 量过] or [旧项[0]]

    # ① 已经量过的那一项不许移
    r1 = server.save_template({"code": tc, "name": "试", "items": ",".join(留)},
                              role="总部运营")
    ck("已经量过的测量项不许从模版里移掉", not r1.get("ok") and r1.get("code") == "ITEM_IN_USE",
       len(量过),
       ("" if not r1.get("ok") else "**移掉之后那批记录会悬空,而悬空不违反任何外键**"))
    if not r1.get("ok"):
        print(f"       挡住了:{r1['reason'][:56]}…")

    # ② 被引用的模版不许删,而且要说清**被谁**引用
    r2 = server.del_template({"code": tc}, role="总部运营")
    说清了 = (not r2.get("ok")) and ("商品挂着它" in (r2.get("reason") or ""))
    ck("被引用的模版不许删,而且要说清被谁引用", 说清了, 1,
       "" if 说清了 else f"实得:{r2}")
    if 说清了:
        print("       **「删不了」三个字没用** —— 看的人还要自己去翻是哪几个商品")

    # ③ 改名/改描述(不动测量项)要放行,并且**报出影响面**
    nm0 = c.execute("SELECT name FROM measure_tpl WHERE code=?", (tc,)).fetchone()[0]
    r3 = server.save_template({"code": tc, "name": nm0 + "·改", "descr": "改了描述",
                               "items": ",".join(旧项)}, role="总部运营")
    有影响面 = r3.get("ok") and "影响面" in (r3.get("reason") or "")
    ck("改名/改描述要放行,并且报出影响面", 有影响面, 1,
       "" if 有影响面 else f"实得:{r3}")

    # ④ 改动要留进编辑日志
    n = c.execute("SELECT COUNT(*) FROM edit_log WHERE obj='量体模板' AND target=?",
                  (tc,)).fetchone()[0]
    ck("模版改动要留进编辑日志", n > 0, 1,
       "" if n else "改了模版却查不到是谁改的 —— 和商品资料一个标准")

    # ⑤ 没有引用的模版**要删得掉** —— 只挡不放行,等于这个功能不存在
    r4 = server.save_template({"name": "临时试删模版", "items": 旧项[0]},
                              role="总部运营")
    新码 = c.execute("SELECT code FROM measure_tpl WHERE name='临时试删模版'").fetchone()
    r5 = server.del_template({"code": 新码[0]}, role="总部运营") if 新码 else {}
    ck("没有引用的模版要删得掉", bool(r5.get("ok")), 1,
       "" if r5.get("ok") else f"建了删不掉:{r4} / {r5}")
    if r5.get("ok"):
        print("       **只挡不放行等于这个功能不存在** —— 两个方向都要测")

    # ⑥ 角色:顾问不许动模版
    r6 = server.save_template({"code": tc, "name": "顾问想改", "items": ",".join(旧项)},
                              role="顾问")
    ck("顾问不许维护量体模版", (not r6.get("ok")) and r6.get("code") == "WRONG_ROLE", 1,
       "" if not r6.get("ok") else f"顾问改成功了:{r6}")
    c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 量体模版管理 6 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
