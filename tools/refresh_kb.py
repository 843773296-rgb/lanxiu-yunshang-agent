#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把知识 md 的改动刷进 craft 表 —— **不重建整个库**。

## 为什么要有它

`knowledge/*.md` 是知识的唯一源头,库由 `seed.py` 从它灌。
而改完 md 之后想让库跟上,原来只有两条路,**两条都不能走**:

    ./tools/rebuild.sh        43 步、删库重建,里面 `seed_triage_samples` **真调模型**跑约半小时
    python3 backend/seed.py   它是重建的**第 1 步**:只跑它得到 65 张表 / 12886 行的空壳
                              (实际在用的库 79 张表 / 198646 行,14 张表根本不存在)

于是实际发生的事是:**改了 md 就不改库**。然后 `knowledge/check_kb.py` 报
「来源等级不一致 —— 以文档为准,**须回改 seed.py**」,而那句提示本身是过期的:
`seed.py` 早就从 `kb.load()` 现读了,不一致只是因为**库没重灌**。

> **一条改了定义的知识,和一条没改的,在库里长得一模一样。**

2026-10-25 立「业务口径」档时撞上这件事:5 条面料的档位和出处在 md 里改好了,
`check_kb` 报 10 处不一致,而没有任何一条命令能只把这 10 处刷进去。

## 它只做一件事

把 `kb.load()` 的结果 UPDATE 进 `craft` 表。**幂等**,只动真有差的行。

⚠️ **不碰 `supplier_code`** —— 那一列不由 md 维护(168 个工艺里只有缂丝 / 妆花 /
苏绣真外发,其余留空是正常的),整行 REPLACE 会把它抹掉。
⚠️ **它写共享库** —— 调用方要先拿锁(`./tools/gate_lock.sh`),这个脚本自己不拿。
⚠️ **它不删**:md 里没有而库里有的,只报出来、不动手 ——
   那可能是别的脚本造的派生行,也可能是 md 删了一条,**两种该做的事相反**。

    python3 tools/refresh_kb.py          只看会改什么(不写)
    python3 tools/refresh_kb.py --做     真写
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "knowledge"))
import kb as _kb                                            # noqa: E402

DB = os.path.join(ROOT, "backend", "lanxiu.db")

# md 解析结果的列名 → craft 表的列名。**两边不同名的只有这三个**,
# 别在这里重抄一份完整列表:`kb.COLS` 才是源(它和建表语句同序)。
改名 = {"lead": "lead_days", "cost": "cost_level", "url": "src_url"}
字段 = _kb.COLS[1:]                                   # code 之外那 11 列
表名 = [改名.get(k, k) for k in 字段]


def 刷(做=False):
    行 = _kb.load()
    if not 行:
        print("❌ md 一条都没解析出来 —— **这不是「没有改动」,是解析坏了**")
        return 2
    c = sqlite3.connect(DB)
    旧 = {r[0]: tuple(r[1:]) for r in
          c.execute(f"SELECT code,{','.join(表名)} FROM craft")}

    新增, 改了, 没变 = [], [], 0
    for row in 行:
        code, 值 = row[0], tuple(row[1:])
        if code not in 旧:
            新增.append(code)
            if 做:
                c.execute(f"INSERT INTO craft(code,{','.join(表名)}) "
                          f"VALUES({','.join('?' * (len(表名) + 1))})", (code, *值))
        elif 旧[code] != 值:
            差 = [k for k, a, b in zip(字段, 旧[code], 值) if a != b]
            改了.append((code, 差))
            if 做:
                c.execute(f"UPDATE craft SET {','.join(n + '=?' for n in 表名)} "
                          f"WHERE code=?", (*值, code))
        else:
            没变 += 1
    多余 = sorted(set(旧) - {r[0] for r in 行})
    if 做:
        c.commit()
    c.close()

    print(f"md {len(行)} 条 · 库 {len(旧)} 条")
    print(f"  没变 {没变} · 要改 {len(改了)} · 要新增 {len(新增)} · md 里没有而库里有 {len(多余)}")
    for code, 差 in 改了[:20]:
        print(f"    ~ {code}  {'/'.join(差)}")
    if len(改了) > 20:
        print(f"    …… 还有 {len(改了) - 20} 条没列出")
    for code in 新增[:10]:
        print(f"    + {code}")
    if 多余:
        # **不删**,只说。md 删了一条、和别的脚本造了一条派生行,
        # 在「库里有而 md 里没有」这件事上长得一模一样,而该做的事相反。
        print(f"  ⚠️ 库里有而 md 里没有:{多余[:10]} —— **本脚本不删**,"
              f"要么是 md 删了一条(那就手工删库里这几行),"
              f"要么是别的脚本造的(那就别管它)")
    if not 做:
        print("\n（只看不写。真要写:python3 tools/refresh_kb.py --做，"
              "并且先拿锁:./tools/gate_lock.sh python3 tools/refresh_kb.py --做）")
    else:
        print(f"\n✅ 已写入({len(改了)} 改 · {len(新增)} 增)")
    return 0


if __name__ == "__main__":
    sys.exit(刷(做="--做" in sys.argv))
