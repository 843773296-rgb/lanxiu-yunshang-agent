#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工确认过的相容矩阵格子 —— **打样核实的结论活不活得过下一次推导**。

业务需求池 P3(待核实 → 知识库的闭环)。归档文件 `knowledge/相容矩阵-人工确认.json`,
读写实现 `backend/combo_manual.py`,推导那头 `knowledge/derive_combo.py`,
写那头是后台的「核实回填」(`server.resolve_combo`)。

## 这套判据的主轴

> **「写回去了」和「写回去的东西活不过下一次推导」,在那条成功返回上长得一模一样。**

2026-10-23 查出来的真相:后台「核实回填」把结论写进库的 `craft_combo`,
而那 16 格「人工确认」**写死在 `derive_combo.py` 的 OVERRIDE 字典里** ——
于是「人确认过的事实」有两个家,**而只有一个家被推导当真**。
回填一格之后,落库对账报

    ❌ 落库漂移 1 格,md 改过但没重新 seed

**那是个错的诊断**(md 一个字没改),而照着它去跑 `seed.py` 会把那格人工确认
**抹掉** —— 那一格回到待核实队列,**而人已经打过样了**(打样是最贵的那种人工)。

> 它红了,所以不是静默的 —— 比静默好得多。
> 但**红错理由比不红更费事**,而这一条更糟:**照着它去做会造成损失。**

## ⚠️ 判据自己造那几种形状

空的 / 重复的 / 结论不合法 / 没理由 —— 这几种在真的归档文件里**一种都不存在**
(它现在是干净的 16 格)。不自己造的话,这几条分支永远走不到,
而「没走到」和「验过了」在绿勾上长得一模一样。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]

G, R, Y, D = "\033[32m", "\033[31m", "\033[32m", "\033[0m"
Rd, Yl = "\033[31m", "\033[33m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


咬合 = [
    # ⚠️ 其中「只写库不写归档」那条,第一版让判据**崩了而不是红了**:
    #    攻击把 `记一格` 删掉,而判据直接 `段.index(...)` → ValueError。
    #    **「崩了」和「被抓到」不是一回事**,而它们在咬合输出上都显示成
    #    「红了但红的不是那一条」。现在先判在不在、再比位置。
    ('把推导里「读不到归档文件就拒跑」改成当 0 格接着推',
     '归档文件读不到:**拒跑**,不许当成「0 格人工确认」'),
    ('让核实回填只写库、不写归档文件',
     '回填必须先写归档文件 —— 只写库的话下一次推导会把它抹掉'),
]

import combo_manual as CM

真档 = CM.档
说明, 格子 = CM.读()
ck("归档文件读得出来(空集合上什么都成立)", len(格子) >= 10, f"只有 {len(格子)} 格")
ck("每一格都有结论、理由、来路",
   all(g.get("结论") in CM.结论们 and (g.get("理由") or "").strip() and g.get("来路")
       for g in 格子),
   f"{[g for g in 格子 if g.get('结论') not in CM.结论们 or not (g.get('理由') or '').strip()][:2]}")
键们 = [(g["工艺"], g["材质"]) for g in 格子]
ck("没有重复的格子(同一格两个结论,谁赢取决于谁写在后面)",
   len(键们) == len(set(键们)),
   f"重复:{[k for k in set(键们) if 键们.count(k) > 1]}")

# ── 推导真的从这份文件读(不是从代码里的字典)────────────────────────
源 = open(os.path.join(ROOT, "knowledge", "derive_combo.py"), encoding="utf-8").read()
ck("推导不再把人工确认写死在代码里",
   "OVERRIDE = _读人工确认()" in 源 and 'OVERRIDE = {\n ("KF01"' not in 源,
   "代码里还有写死的 OVERRIDE 字典 —— 那就又是两个家")
ck("推导和回填**共用一份读写实现**(不是各写一份解析)",
   "import combo_manual" in 源,
   "各写一份的话,两边对「同一格两条」「结论只能三种」的判断迟早不一致,"
   "而不一致时没人知道哪边对")

# ── ⚠️ 判据自己造那几种危险形状,在**临时文件**上跑推导 ────────────────
#
# 真的归档文件现在是干净的 16 格,所以下面这几种分支在它上面永远走不到。
def 跑推导(改档):
    """把归档文件换成 `改档` 再跑一次推导 → (退出码, 输出)。

    ⚠️ **动的是环境变量指过去的临时文件,不是真档** —— 今天刚因为
    「以为在副本上、其实指着真的」往共享库误写过一格。
    这里用 `--人工确认档` 不行(推导没这个参数),所以**整份仓库都不碰**:
    把临时档拷到真档的位置之前先备份,跑完无论如何还原(finally)。
    """
    备 = 真档 + ".检查备份"
    shutil.copy(真档, 备)
    try:
        shutil.copy(改档, 真档)
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "knowledge", "derive_combo.py")],
                           capture_output=True, text=True, cwd=ROOT)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    finally:
        shutil.copy(备, 真档)
        os.remove(备)


tmp = tempfile.mkdtemp()


def 写临时(格子们):
    p = os.path.join(tmp, f"t{len(os.listdir(tmp))}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"_说明": ["检查造的"], "格子": 格子们}, f, ensure_ascii=False)
    return p


码, 出 = 跑推导(写临时([]))
ck("归档文件是空的:**拒跑**,不许当成「0 格人工确认」",
   码 != 0 and "一格都没有" in 出,
   f"退出码 {码} —— 当成 0 格的话那些格子会被规则重新填一遍,"
   f"**而那个结果看起来完全正常**(273 格全有判定),"
   f"只是人打样的判断被规则的猜测换掉了")

两条 = [dict(格子[0]), dict(格子[0])]
两条[1]["结论"] = "不可"
码, 出 = 跑推导(写临时(两条))
ck("同一格两条:**拒跑**", 码 != 0 and "出现了两次" in 出,
   f"退出码 {码} / {出[-200:]}")

坏结论 = [dict(格子[0], 结论="大概可以")]
码, 出 = 跑推导(写临时(坏结论))
ck("结论不是「可 / 不可 / 需评估」:**拒跑**", 码 != 0 and "只能是" in 出,
   f"退出码 {码} / {出[-160:]}")

没理由 = [dict(格子[0], 理由="   ")]
码, 出 = 跑推导(写临时(没理由))
ck("没有理由的「人工确认」:**拒跑**(和默认放行没区别)",
   码 != 0 and "没有理由" in 出, f"退出码 {码} / {出[-160:]}")

# 文件不在 → 拒跑。**不许当成 0 格**
备 = 真档 + ".检查挪开"
shutil.move(真档, 备)
try:
    r = subprocess.run([sys.executable, os.path.join(ROOT, "knowledge", "derive_combo.py")],
                       capture_output=True, text=True, cwd=ROOT)
    出 = (r.stdout or "") + (r.stderr or "")
    ck("归档文件读不到:**拒跑**,不许当成「0 格人工确认」",
       r.returncode != 0 and "拒跑" in 出, f"退出码 {r.returncode} / {出[-200:]}")
finally:
    shutil.move(备, 真档)

# ── 回填那一头:必须先写归档文件 ────────────────────────────────────
srv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
i = srv.index("def resolve_combo(")
j = srv.index("\ndef ", i + 10)
段 = srv[i:j]
# ⚠️ **先判在不在,再比位置。** 第一版直接 `段.index("记一格")` ——
# 咬合把那一句删掉之后,判据**抛 ValueError 崩了**,而不是红。
# > 「崩了」和「被抓到」不是一回事,而它们在咬合输出上都显示成
# > 「红了但红的不是那一条」。
有记一格 = "记一格" in 段 and "combo_manual" in 段
有改库 = "UPDATE craft_combo" in 段
ck("回填必须先写归档文件 —— 只写库的话下一次推导会把它抹掉",
   有记一格 and 有改库 and 段.index("记一格") < 段.index("UPDATE craft_combo"),
   f"写归档在不在={有记一格} 改库在不在={有改库} —— "
   "回填里找不到写归档文件,或者它写在改库**之后** —— "
   "顺序是有意的:文件写失败就整个拒,**不留下「库里有、文件里没有」的格子**,"
   "那正是那个错诊断的来源")
ck("写归档失败 → 整个回填拒掉(不留半成品)",
   "ARCHIVE_FAIL" in 段, "没有这一支:写不进文件却照样改了库")
ck("返回里告诉人「那份文件要提交进版本库」",
   "提交" in 段 and "归档" in 段,
   "不说的话,重建一次库这一格就回到「没有依据」,而人已经打过样了")
# 那句已经不成立的理由不许留着
ck("不再拿「工具层一个写接口都没有」当理由(写工具现在 28 个)",
   "工具层一个写接口都没有」那条保证不能" not in 段,
   "**那句话早就不是真的了** —— 拿一个假前提当设计理由,"
   "下一个人照着它推出来的结论也是假的")

shutil.rmtree(tmp, ignore_errors=True)
print("=" * 80)
if bad:
    print(f"{Rd}❌ {len(bad)} 条没过:{bad}{D}")
    sys.exit(1)
print(f"{G}✅ 打样核实的结论活得过推导(验了 {n} 条){D}")
print(f"    归档文件 {len(格子)} 格 —— **它和 md 一样是手写源、进版本库**,"
      f"推导只读它;重建一次库,结论还在文件里。")
sys.exit(0)
