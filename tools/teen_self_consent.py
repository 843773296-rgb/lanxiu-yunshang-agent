#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 14—18 周岁的着装人补「本人签」的身体数据同意(业务 2026-10-10 晚 #9:14—18 周岁以本人同意为准)。

    python3 tools/teen_self_consent.py          # 只看
    python3 tools/teen_self_consent.py --做     # 真写(幂等:补过的不再补)
    python3 tools/teen_self_consent.py --回滚   # 按前缀删掉(CST)

## 为什么要补

三个造数入口(seed.py / grow_customers.py / fix_order_measure.py)都按「未满 18 → 监护人签」造同意,
于是 2026-10-10 量:存了身体数据的 14—17 岁着装人 95 位,**本人签的 0 份**。
新规矩(knowledge/consent_age.py)上线后,这 95 位**一个都量不了** —— 而在真实门店里,
他们只是还没让孩子本人签。这一步模拟的就是「孩子本人在门店补签了」。

**为什么不去改那三个造数入口**:同意的编号是按顺序数出来的(CS{2000+n}),
在中间多插一条,后面所有编号整体错位,牵连到写死编号的夹具。
所以补在**最后一步**、编号单独起头(CST + 着装人编号),前面一行不动。

补的这一份:签署日期、渠道**照抄家长那一份** —— 当时就该一起签,不另编一个日子;
家长那一份原样保留,它就是「家长付款时身体数据那项家长也确认」的那一签(双签)。

年龄按**世界今天**算(worldclock),所以要排在 shift_world 之后。
每天都有孩子满 14 岁 —— 他们会在下一次跑这一步时补上;**在那之前量不了,这是对的**
(真实门店里满 14 岁之后第一次量体,就该让孩子本人签)。
"""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import worldclock
import consent_age

DB = os.path.join(ROOT, "backend", "lanxiu.db")
前缀 = "CST"


def 要补的(c, 今天):
    出 = []
    for wid, 名, 生日 in c.execute("SELECT id, name, birthday FROM wearer WHERE birthday IS NOT NULL "
                                  "AND date(birthday, '+14 years') <= ? AND date(birthday, '+18 years') > ?",
                                  (今天, 今天)).fetchall():
        有 = c.execute("SELECT relation, channel, granted_at FROM consent WHERE wearer_id=? AND scope='身体数据' "
                      "AND revoked_at IS NULL ORDER BY granted_at", (wid,)).fetchall()
        if not 有 or any(r == consent_age.本人 for r, _, _ in 有):
            continue                     # 没有身体数据(不需要) / 本人已经签过
        家 = next((x for x in 有 if consent_age.是家长(x[0])), 有[0])
        出.append((f"{前缀}{wid}", wid, 名, 家[1], 家[2]))
    return 出


def main():
    c = sqlite3.connect(DB)
    if "--回滚" in sys.argv:
        n = c.execute("DELETE FROM consent WHERE id LIKE ?", (前缀 + "%",)).rowcount
        c.commit()
        print(f"删掉 {n} 条补签")
        return
    今天 = worldclock.今天().isoformat()
    补 = 要补的(c, 今天)
    print(f"世界今天 {今天}:14—18 周岁、有身体数据、本人还没签的着装人 {len(补)} 位")
    if "--做" not in sys.argv:
        print("(只看。真写加 --做)")
        return
    c.executemany("INSERT OR IGNORE INTO consent(id, wearer_id, scope, granted_by, relation, channel, granted_at) "
                  "VALUES(?,?,'身体数据',?,'本人',?,?)", 补)
    c.commit()
    print(f"补了 {len(补)} 份本人签的身体数据同意(家长那份原样保留,即双签)")


if __name__ == "__main__":
    main()
