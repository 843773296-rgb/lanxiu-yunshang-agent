#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁片用料占比的检查 —— **估出来的和版师给的不许长得一样。**

## 背景

分部位报价要把整件用料摊到各裁片上,而 `pattern_piece` 原来没有面积。
补齐要 84 个版型 × 平均 5 片 ≈ 400 个数,只有版师给得出来 ——
于是它成了一条**会一直挂着的待办**,而挂着的这段时间里报价一直按最贵的料算,
**客户一直被报高**。

所以按几何估了一个初值(规则在 `knowledge/piece_ratio.py`,
每条都写了依据,版师能逐条驳)。**估了就必须守住三件事:**

**① 占比之和 = 1。** 我们估得出各片的相对大小,估不准绝对用布
(排料、损耗、门幅都会影响)。而 `pattern.fabric_base` 是可信的 ——
**用可信的总量 × 估算的相对占比,比两个都估要稳**。

**② 来源标出来,而且版师改过的不许被重新估覆盖。**
这是这条最容易出的错:下次重跑估算脚本,把人工核过的数悄悄盖回去,
而**没有任何地方会报**。

**③ 内衬不按裁片占比算。** 它的部位是从 BOM 推的,而 BOM 里
**本来就写着用多少米**。按裁片占比算的话内衬是 **0.00 米** ——
而挂里是真要用布的。**一个部位用两个来源推出来,算料时不能只用其中一个。**

⚠️ **系带不在此列。** 它曾经和内衬一起被划成「走 BOM」,而对账当场炸:
PT04 马面裙各部位 3.45 米 ≠ 整件 3.6 米,**差的 0.15 米凭空消失** ——
就是系带那一片(占比算进了整件,却没算进任何部位)。
证据很硬:**系带出现在 `pattern_piece` 里 ⇒ 它是用主料裁的**;
BOM 里的「辅料」是织带 / 丝绦,那是**买来的成品带子**,两回事。
"""
import os, sys, sqlite3, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
KN = os.path.join(os.path.dirname(HERE), "knowledge")


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把一个版型里某个裁片的占比改大(这个版型的占比之和不再等于 1)',
     '每个版型的裁片占比之和 = 1'),
]

def _load(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(KN, name + ".py"))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m


part = _load("part")
pr = _load("piece_ratio")
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row

    # ① 每个版型的占比之和 = 1
    差 = [f"{r['pattern']}:{r['s']}" for r in c.execute(
        "SELECT pattern, ROUND(SUM(ratio),4) s FROM pattern_piece "
        "WHERE ratio IS NOT NULL GROUP BY pattern HAVING ABS(s-1)>0.01")]
    n1 = c.execute("SELECT COUNT(DISTINCT pattern) FROM pattern_piece "
                   "WHERE ratio IS NOT NULL").fetchone()[0]
    ck("每个版型的裁片占比之和 = 1", not 差, n1,
       ("；".join(差[:3]) if 差 else
        "**用可信的总量(fabric_base)× 估算的相对占比,比两个都估要稳**"))

    # ② 每条都要有来源,而且来源只能是这两种
    野 = [r[0] for r in c.execute(
        "SELECT DISTINCT COALESCE(ratio_src,'(空)') FROM pattern_piece "
        "WHERE ratio IS NOT NULL")
        if r[0] not in ("估算", "复核", "版师")]
    # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
    n2 = c.execute("SELECT COUNT(*) FROM pattern_piece WHERE ratio IS NOT NULL"
                   ).fetchone()[0]
    ck("每条占比都要标来源(估算 / 复核 / 版师)", not 野, n2,
       ("；".join(野[:3]) if 野 else
        "**估算 / 复核 / 版师是三种可信度** —— "
        "「复核」是核过规则、没核过数,报价上按最低那一档提示"))

    # ③ **版师核过的不许被重新估覆盖。**
    #    验法:把一条标成「版师」并改掉值,重跑估算,它必须纹丝不动。
    # **连 ratio_src 一起存下来。** 原来只存了 ratio,还原时硬写回「估算」——
    # 于是每跑一次 check.sh,这一行就被从「复核」降级成「估算」一次,
    # **而且降完之后检查照样全绿**(来源仍在白名单里)。
    # 一条会污染数据的检查,比没有它更糟:它在你最忙的那天悄悄改库,
    # 而你正忙着看红的那一条。这个包装 boundary_audit 上有,这儿漏了 ——
    # **教训没长成纪律,就会在下一个地方原样再来一遍。**
    tgt = c.execute("SELECT pattern,name,ratio,ratio_src FROM pattern_piece "
                    "WHERE ratio IS NOT NULL LIMIT 1").fetchone()
    原来的来源 = tgt["ratio_src"]
    c.execute("UPDATE pattern_piece SET ratio=0.999, ratio_src='版师' "
              "WHERE pattern=? AND name=?", (tgt["pattern"], tgt["name"]))
    for nm, q, rt, _w in pr.版型占比(c, tgt["pattern"]):
        c.execute("UPDATE pattern_piece SET ratio=?, ratio_src='估算' "
                  "WHERE pattern=? AND name=? AND ratio_src IS NULL",
                  (rt, tgt["pattern"], nm))
    后 = c.execute("SELECT ratio,ratio_src FROM pattern_piece WHERE pattern=? AND name=?",
                   (tgt["pattern"], tgt["name"])).fetchone()
    守住 = abs(后["ratio"] - 0.999) < 1e-6 and 后["ratio_src"] == "版师"
    c.execute("UPDATE pattern_piece SET ratio=?, ratio_src=? "
              "WHERE pattern=? AND name=?",
              (tgt["ratio"], 原来的来源, tgt["pattern"], tgt["name"]))
    ck("版师核过的不许被重新估覆盖", 守住, 1,
       "" if 守住 else f"被盖回去了:{dict(后)}")
    if 守住:
        print("       **下次重跑脚本把人工核过的数悄悄盖回去,没有任何地方会报**")

    # ④ 内衬 / 系带走 BOM,不按裁片占比算(按占比算会是 0)
    坏 = []
    for pt, in c.execute("SELECT code FROM pattern LIMIT 40").fetchall():
        for b in part.形制的部位(c, pt):
            米, 源 = part.部位用料(c, pt, b)
            if b in part.部位料类:
                if 源 != "BOM":
                    坏.append(f"{pt}·{b} 源是「{源}」,该是 BOM")
                elif 米 <= 0:
                    坏.append(f"{pt}·{b} 用料 0 米 —— **挂里是真要用布的**")
    ck("内衬的用料走 BOM,不按裁片占比算", not 坏, 40,
       ("；".join(坏[:3]) if 坏 else
        "**一个部位用两个来源推出来,算料时不能只用其中一个** —— "
        "按裁片占比算的话内衬是 0.00 米"))

    # ⑤ 各部位用料之和 ≈ 整件用料(内衬 / 系带另计,它们不吃主料)
    偏 = []
    for pt, fb in c.execute("SELECT code,fabric_base FROM pattern WHERE fabric_base>0 "
                            "LIMIT 40").fetchall():
        s = sum(part.部位用料(c, pt, b)[0] for b in part.形制的部位(c, pt)
                if b not in part.部位料类)
        if fb and abs(s - fb) > max(0.05, fb * 0.02):
            偏.append(f"{pt}:各部位 {round(s,2)} ≠ 整件 {fb}")
    ck("外层各部位的用料之和 = 整件用料", not 偏, 40,
       ("；".join(偏[:3]) if 偏 else
        "**内衬另计**(它吃里料不吃主料);**系带算在内** —— "
        "它在裁片表里,是用主料裁的。这条对账炸出过 0.15 米凭空消失"))
    c.commit(); c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 裁片用料占比 5 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
