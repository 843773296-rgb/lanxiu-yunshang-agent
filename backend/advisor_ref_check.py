# -*- coding: utf-8 -*-
"""顾问引用的检查 —— **所有存员工的地方只存工号,而且工号必须真有这个人。**

## 这份检查原来守什么、为什么改(2026-10-11,用户批准按建议改)

原来守的是「名字是被钉住的缓存」:九张表约 2160 行存着「A04 陆微」这样的字符串,
名字一改历史全断,所以每张表配一个 `*_no` 工号,检查盯着名字和工号不许漂。

后来**名字列全删了**(页面改成 join staff 取名字)—— 那个风险从根上没了,
而这份检查的 ⓪①③ 三条都改成了「扫到 0 张表」。它自带的「样本量 0 不叫通过」正好抓住了自己,
但**它从来没进过门禁**(check.sh / tools/*.sh / CI 一处都没调),所以没人看见。
数据工厂 10-11 挖出来的:手跑退出码 1,烂了两处 —— 0 张表、以及没排掉反例夹具 FX-BAD-01。

## 现在守四条

⓪ **名字列不许长回来** —— 删掉的风险,得有人盯着它不复活
① **工号列从库结构现算**,不从映射表抄 —— 映射写着 11 张,库里其实 14 张(商机 / 评价 / 报价后来加的,
   从没进过这份检查的视野:**一条检查的覆盖范围,不能靠写在文档里的那个数**,原版 ⓪ 的教训照旧)
② 工号都在员工表里 —— **只豁免点名的反例夹具**,而且豁免要能自证还活着(见下)
③ `schedule` 的两个工号字段一致
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAIL = []

工号列名 = ("advisor_no", "measured_by_no", "assignee_no")
名字列名 = ("advisor", "measured_by")

# ── 豁免:**故意**存着查不到的工号的反例夹具 ─────────────────────────────
# 每条写清谁要它、为什么。⚠️ **豁免不许囤积**:夹具没了、或者要它的那条检查不再点它,就红 ——
# 一条豁免掉的东西已经不存在了还留着,下一个人会以为「这里有个例外」,而那个例外是空的。
豁免 = [
    dict(表="customer", id="FX-BAD-01", 列="advisor_no",
         谁要="backend/ownership_check.py",
         为什么="归属检查「工号在员工表里查不到 → NO_SUCH(数据要修)」那条分支的反例夹具,"
                "由 tools/backfill_fixtures.py 摆;没有它那条分支一次都走不到"),
]

咬合 = [
    ("豁免名单清空(反例夹具那个查不到的工号该被抓出来)", "工号都在员工表里"),
    ("豁免指向一个不存在的夹具", "每条豁免都还活着"),
    ("把一个工号列当成名字列(等于名字列长回来了)", "名字列没有长回来"),
]


def ck(name, ok, n, msg="", 可以为零=False):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0 and not 可以为零:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main(db=None):
    print("顾问引用 · 检查")
    print("=" * 84)
    c = sqlite3.connect(f"file:{db or os.path.join(HERE, 'lanxiu.db')}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    全员 = {r["no"] for r in c.execute("SELECT no FROM staff")}
    表们 = [t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    列 = {t: [x[1] for x in c.execute(f"PRAGMA table_info({t})")] for t in 表们}

    # ⓪ 名字列不许长回来
    长回来 = sorted(f"{t}.{x}" for t in 表们 for x in 列[t] if x in 名字列名)
    ck("名字列没有长回来(只存工号,名字 join staff 现取)", not 长回来, len(表们),
       f"又有了 {长回来} —— **名字副本一改历史全断**,这正是当初删掉它们的原因" if 长回来 else
       f"扫了 {len(表们)} 张表")

    # ① 工号列从库结构现算
    工号列 = [(t, x) for t in 表们 for x in 列[t] if x in 工号列名]
    ck("库里存员工工号的列(从库结构现算,不从映射表抄)", len(工号列) >= 10, len(工号列),
       "、".join(f"{t}.{x}" for t, x in 工号列))

    # ② 工号都在员工表里 —— 只豁免点名的夹具,而且豁免要自证还活着
    豁免键 = {(x["表"], x["id"], x["列"]) for x in 豁免}
    n2 = 0; 野 = []
    for t, x in 工号列:
        有id = "id" in 列[t]
        for r in c.execute(f"SELECT {'id' if 有id else 'rowid'} AS k, {x} AS no FROM {t} WHERE {x} IS NOT NULL"):
            n2 += 1
            if r["no"] not in 全员 and (t, r["k"], x) not in 豁免键:
                野.append((t, x, r["k"], r["no"]))
    ck("工号都在员工表里(只豁免点名的反例夹具)", not 野, n2,
       f"查不到的 {len(野)} 处,例:{野[:3]}" if 野 else f"豁免 {len(豁免)} 条:{[x['id'] for x in 豁免]}")

    死豁免 = []
    for x in 豁免:
        还在 = x["列"] in 列.get(x["表"], []) and c.execute(
            f"SELECT 1 FROM {x['表']} WHERE id=? AND {x['列']} IS NOT NULL", (x["id"],)).fetchone()
        还有人要 = x["id"] in open(os.path.join(os.path.dirname(HERE), x["谁要"]), encoding="utf-8").read()
        if not (还在 and 还有人要):
            死豁免.append(f"{x['id']}({'夹具不在库里了' if not 还在 else x['谁要'] + ' 不再用它'})")
    ck("每条豁免都还活着(夹具在库里、要它的检查还点着它)", not 死豁免, len(豁免),
       f"该删的豁免 {死豁免} —— **豁免不许囤积**" if 死豁免 else "")

    # ③ schedule 的两个工号字段一致 —— 两边都是工号、格式一样,对不上肉眼看不出
    n4 = c.execute("SELECT COUNT(*) FROM schedule WHERE assignee_no IS NOT NULL "
                   "AND advisor_no IS NOT NULL").fetchone()[0]
    不一致 = c.execute("SELECT id, assignee_no, advisor_no FROM schedule WHERE assignee_no IS NOT NULL "
                    "AND advisor_no IS NOT NULL AND assignee_no!=advisor_no LIMIT 3").fetchall()
    ck("schedule 的两个工号字段一致", not 不一致, n4,
       f"对不上,例:{[tuple(r) for r in 不一致]}" if 不一致 else "「一个人两套编号」那个 bug 就是从这儿来的")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 顾问引用全过(验了 {n2} 个工号)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
