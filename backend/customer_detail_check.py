#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户详情 · 顾问名字和日历的「今天」 · 检查(10-19 外部复审 3.3)。

复审看到:同一个客户在列表有顾问,详情的「销售顾问」是空的 —— 库里只存工号,列表过了 `填顾问名`、详情没过;
跟进记录也一样。日历写死 2026-08-31,数据每天平移,日历一直停在 8 月。
`advisor_name_check` 扫不到详情:它只调「一个参数、给空也能跑」的页面函数,详情要客户号,调不起来就跳过了。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("详情不按工号补顾问名", "详情的销售顾问 = 员工表里这个工号的名字"),
    ("详情不给世界的今天", "详情接口给出世界的今天,页面日历用它"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("客户详情 · 顾问名字和日历的「今天」")
print("=" * 80)
import server as SV, worldclock

c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
# 挑一位**有跟进记录、顾问工号在员工表里**的客户;没有就没验,不算通过
r = c.execute("""SELECT cu.id, cu.advisor_no, s.name FROM customer cu JOIN staff s ON s.no=cu.advisor_no
                 WHERE EXISTS (SELECT 1 FROM followup f JOIN staff s2 ON s2.no=f.advisor_no WHERE f.customer_id=cu.id)
                 ORDER BY cu.id LIMIT 1""").fetchone()
名册 = dict(c.execute("SELECT no, name FROM staff"))
c.close()
if not r:
    ck("库里有一位带跟进记录、顾问在员工表里的客户 —— 没有就没验,不算通过", False)
else:
    cid, 工号, 名 = r
    d = SV.customer_detail(cid)
    # 显示格式和列表一致:「A03 沈砚」(简码 + 名字),所以认「以这个名字结尾」
    ck("详情的销售顾问 = 员工表里这个工号的名字", str(d["customer"].get("advisor") or "").endswith(名), (cid, 工号, d["customer"].get("advisor")))
    跟 = [(f.get("advisor_no"), f.get("advisor")) for f in d["followups"] if f.get("advisor_no") in 名册]
    ck("跟进记录的顾问也按工号补上了名字", 跟 and all(str(a or "").endswith(名册[no]) for no, a in 跟), 跟[:3])
    ck("详情接口给出世界的今天,页面日历用它", d.get("今天") == worldclock.今天().isoformat(), d.get("今天"))
页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
ck("页面不再写死日历日期(2026-08-31),从详情接口取",
   'DEMO_TODAY="2026-08-31"' not in 页 and "DEMO_TODAY=d.今天" in 页)

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 客户详情:顾问名字按工号现取、日历的今天是世界的今天(验了 {n} 条){D}")
