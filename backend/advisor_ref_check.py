# -*- coding: utf-8 -*-
"""顾问引用的检查 —— **名字是被钉住的缓存,不是第二份真相。**

**九张表**约 2160 行存着「A04 陆微」这样的字符串。名字一改
(结婚改姓、录错一个字)—— **所有历史记录当场断掉,而且悄无声息**。

现在每张表都有 `*_no` 指向工号 —— ⚠️ **这句话一度是假的**:
2026-09-15 之前 `customer` / `delivery_notice` / `scheme` 三张
根本没有引用列,也就从来没进过这份检查。第 ⓪ 条就是为此加的。
名字列**暂时留着**(38 个页面在显示它),
但它是有检查盯着的缓存:

    **一个被钉住的副本,和一个自由漂移的副本,是两件事。**

彻底删掉名字列要等页面改成 join staff 取名字。**留着不写清楚才危险**,
所以这条检查存在的意义就是:在那天到来之前,不许它漂。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fix_advisor_ref as FX
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("顾问引用 · 检查")
    print("=" * 84)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    全员 = {r["no"]: r["name"] for r in c.execute("SELECT no,name FROM staff")}

    # ── ⓪ **映射表本身有没有漏表** ────────────────────────────────────
    #
    # 这条是 2026-09-15 补的,而它补上的当天就抓到三张:
    # `customer`(106 行,「这个客户归谁跟」)、`delivery_notice`、`scheme`
    # —— 它们有 `advisor` 列却**从来没建过引用**,也就从来没进过这份检查的视野。
    #
    # 三个数当时没有一个对得上:迁移脚本的文档写「七张表」、映射里六张、
    # 库里有这一列的九张。**而我们以为这笔债被盯着** ——
    # 其实最大的那一张从来没进过账本。
    #
    # **一条检查的覆盖范围,不能靠写在文档里的那个数。** 这里拿库现算。
    有列 = set()
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if any(x[1] == "advisor" for x in c.execute(f"PRAGMA table_info({t})")):
            有列.add(t)
    覆盖 = {t for t, 名列, _ in FX.映射 if 名列 == "advisor"}
    漏 = sorted(有列 - 覆盖)
    ck("库里每一张有 advisor 列的表,映射里都有", not 漏, len(有列),
       f"漏了 {漏} —— **它们的名字在自由漂移,而且没人盯着**" if 漏 else
       f"{len(有列)} 张全在(另有 measure_rec.measured_by 走同一套)")

    # ① 每一行有名字的,都要有工号 —— **不许只有名字**。
    n1 = 缺 = 0; 例1 = []
    for t, 名列, 号列 in FX.映射:
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        if 名列 not in cols or 号列 not in cols: continue
        r = c.execute(f"SELECT COUNT(*) a, SUM({号列} IS NULL) b FROM {t} "
                      f"WHERE {名列} IS NOT NULL").fetchone()
        n1 += r["a"]; 缺 += (r["b"] or 0)
        if r["b"]: 例1.append((t, r["b"]))
    ck("有名字的行都补上了工号", 缺 == 0, n1, f"缺的 {例1}" if 缺 else
       "名字一改,只有名字的那些当场断掉")

    # ② 工号必须真实存在。
    n2 = 野 = 0; 例2 = []
    for t, 名列, 号列 in FX.映射:
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        if 号列 not in cols: continue
        for r in c.execute(f"SELECT DISTINCT {号列} AS no FROM {t} WHERE {号列} IS NOT NULL"):
            n2 += 1
            if r["no"] not in 全员:
                野 += 1
                if len(例2) < 3: 例2.append((t, r["no"]))
    ck("工号都在员工表里", 野 == 0, n2, f"野的 {例2}" if 野 else "")

    # ③ **名字和工号必须一致** —— 这是「缓存被钉住」的那颗钉子。
    #    漂了当场红:名字改了而工号没跟、或者反过来。
    n3 = 漂 = 0; 例3 = []
    for t, 名列, 号列 in FX.映射:
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        if 名列 not in cols or 号列 not in cols: continue
        for r in c.execute(f"SELECT {名列} AS tag,{号列} AS no FROM {t} "
                           f"WHERE {名列} IS NOT NULL AND {号列} IS NOT NULL"):
            n3 += 1
            want = 全员.get(r["no"])
            tag = str(r["tag"]).strip()
            # 名字列可能是「A04 陆微」也可能直接是工号 —— 两种都得对得上
            ok = (want and want in tag) or tag == r["no"]
            if not ok:
                漂 += 1
                if len(例3) < 3: 例3.append((t, tag, r["no"], want))
    ck("名字和工号一致(缓存没漂)", 漂 == 0, n3,
       f"漂了 {例3}" if 漂 else
       "**一个被钉住的副本,和一个自由漂移的副本,是两件事**")

    # ④ `schedule` 那两个工号字段也得一致 —— 它**同时**有
    #    `assignee_no`(隔离判定用的)和新加的 `advisor_no`。
    #    **两个工号字段对不上,比一个名字一个工号更隐蔽**:
    #    两边都是工号,格式一样,肉眼扫过去看不出。
    n4 = c.execute("SELECT COUNT(*) FROM schedule WHERE assignee_no IS NOT NULL "
                   "AND advisor_no IS NOT NULL").fetchone()[0]
    不一致 = [dict(r) for r in c.execute(
        "SELECT id,assignee_no,advisor_no FROM schedule "
        "WHERE assignee_no IS NOT NULL AND advisor_no IS NOT NULL "
        "AND assignee_no!=advisor_no")]
    ck("schedule 的两个工号字段一致", not 不一致, n4,
       f"对不上 {len(不一致)} 条,例:{不一致[:2]}" if 不一致 else
       "「一个人两套编号」那个 bug 就是从这儿来的")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 顾问引用 4 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
