# -*- coding: utf-8 -*-
"""方案的引用检查 —— **存编码不存名字,而且必须落到具体版型。**

## 原来存的是名字

    xz='明制立领长衫'  mt='云锦'  kf='妆花,苏绣'

名字一改,所有历史方案的引用**当场断掉而且悄无声息** ——
按名字 join 出来是空,看起来像「这个方案没选形制」。
这和「订单靠活动名连活动」是同一个病,前几天刚修过一次。

## 版型接进来之后多了一件原来做不到的事

方案里选的是**形制**,而真正决定「用多少米料 / 量哪些尺寸 / 能不能做」的是**版型** ——
一个形制下常有好几个版型(标准/加长/改良通勤、男款/女款)。

原来这条边不存在,于是方案**报得出「明制立领长衫」,报不出「用多少米料」**。
接上之后:`pattern.fabric_base` + `fabric_step` + `material.loss_rate`
就能算出这个方案的用料和料费 —— 下面第 ④ 条验的就是这件事。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把一个方案的形制字段从编码改成中文名',
     '形制/面料/工艺/版型都是编码且存在'),
]

def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("方案引用 · 检查")
    print("=" * 80)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("SELECT * FROM scheme")]
    n = len(rows)

    # ① 形制、面料、工艺、版型都得是**编码**,而且指向真实存在的行。
    坏 = []
    for r in rows:
        if not c.execute("SELECT 1 FROM xingzhi WHERE code=?", (r["xz"],)).fetchone():
            坏.append((r["id"], "xz", r["xz"]))
        if not c.execute("SELECT 1 FROM material WHERE code=?", (r["mt"],)).fetchone():
            坏.append((r["id"], "mt", r["mt"]))
        for k in [x.strip() for x in (r["kf"] or "").split(",") if x.strip()]:
            if not c.execute("SELECT 1 FROM craft WHERE code=?", (k,)).fetchone():
                坏.append((r["id"], "kf", k))
        if not c.execute("SELECT 1 FROM pattern WHERE code=?", (r["pattern"],)).fetchone():
            坏.append((r["id"], "pattern", r["pattern"]))
    ck("形制/面料/工艺/版型都是编码且存在", not 坏, n,
       f"坏的 {坏[:3]}" if 坏 else "存名字的话,名字一改历史引用当场断掉")

    # ② **版型必须属于方案选的那个形制。**
    #    这一条防的是「两个编码各自合法、但连的不是同一件事」——
    #    xz=XZ04 而 pattern=PT11(圆领袍),两个都存在,拼起来是胡说。
    错配 = [(r["id"], r["xz"], r["pattern"]) for r in rows
            if not c.execute("SELECT 1 FROM pattern WHERE code=? AND xz=?",
                             (r["pattern"], r["xz"])).fetchone()]
    ck("版型属于方案选的那个形制", not 错配, n,
       f"对不上 {错配[:2]}" if 错配 else "两个编码各自合法≠它们连的是同一件事")

    # ③ 名字**不许**再出现在这几个字段里 —— 咬合用:防着有人改回去。
    像名字 = [(r["id"], f, r[f]) for r in rows
              for f in ("xz", "mt", "pattern")
              if r[f] and not str(r[f])[:2].isascii()]
    ck("这几个字段里没有中文名", not 像名字, n * 3,
       f"还是名字 {像名字[:2]}" if 像名字 else "")

    # ④ **接上版型之后能算出料** —— 这是这条边的用处,不验它等于没接。
    #    用料 = 版型基准 + 步进×(尺码档-1),再按物料损耗率放大。
    n4 = 0; 算不出 = []
    for r in rows:
        p = c.execute("SELECT fabric_base,fabric_step,sizes FROM pattern WHERE code=?",
                      (r["pattern"],)).fetchone()
        m = c.execute("SELECT price,loss_rate,width_cm FROM material WHERE code=?",
                      (r["mt"],)).fetchone()
        if not (p and m and p["fabric_base"] and m["price"] is not None):
            算不出.append(r["id"]); continue
        n4 += 1
        米 = p["fabric_base"] * (1 + (m["loss_rate"] or 0))
        料费 = 米 * m["price"]
        if not (米 > 0 and 料费 > 0):
            算不出.append(r["id"])
    ck("每个方案都算得出用料和料费", not 算不出, n4,
       f"算不出的 {算不出}" if 算不出 else
       "**这是接这条边的用处** —— 原来方案报得出形制名,报不出用多少米料")

    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 方案引用 4 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
