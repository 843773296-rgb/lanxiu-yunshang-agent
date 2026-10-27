#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纹样业务核定 · 检查 —— **人核过的不许被重算覆盖,而模型不许替人核。**

两件事分开验:

1. **覆盖层对不对**:`motif_review.定()` 核定优先于 `motif.推()`,
   核过的商品从「待业务核」清单里消失。
2. **写口拦不拦住模型**:这个工具的处境和 `set_piece_ratio` 不同 ——
   裁片用料占比模型猜不出数,**纹样它张口就来**。所以写口校验用户原话,
   原话里没出现那个纹样的说法就不写。
   > 一条「用户定的纹样」和一条「模型替用户猜的纹样」,
   > **在库里长得一模一样** —— 而后者会被当成人核过的、永不重算。

⚠️ 跑在**库副本**上,不碰 `backend/lanxiu.db`:
先 import 写口再切 `api.DB`(之后才 import 的写口会写真库),切完当场断言。
副本用 `sqlite3.backup()` 不用 `cp` —— `lanxiu.db` 是软链。
"""
import os, sys, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))

import api, motif_review as mr, motif      # ← 先 import,再切库

# 咬合 —— **改坏的是什么、该红的是哪一条**,只写「测过了」和没写是一回事。
# (可执行的那三条在 `tools/bite_specs.json` 里,跑法:
#  `python3 tools/bite_run.py --only "backend/motif_review_check.py"`)
咬合 = [
    ("把 api.review_motif 里校验用户原话那一支改成 `if False:`",
     "原话里没出现那个纹样的说法 → 拒"),
    ("把 motif_review.定() 里「核定优先」那一支改成 `if False:`",
     "核过之后 `定()` 返回核定值,不是推算值"),
    ("把 api.review_motif 里的角色判断改成 `if False:`",
     "顾问身份 → 拒(要总部运营)"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0


def ck(名, 得, 应):
    global n
    n += 1
    ok = (得 == 应) if not callable(应) else 应(得)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  得到={得!r}"))
    if not ok:
        坏.append(名)


真DB = api.DB
if not os.path.exists(真DB):
    print("ℹ️ 库不在 —— **这一轮没验**(不是验过了)")
    sys.exit(0)

副本 = os.path.join(tempfile.mkdtemp(), "lanxiu.db")
_s, _d = sqlite3.connect(f"file:{真DB}?mode=ro", uri=True), sqlite3.connect(副本)
with _d:
    _s.backup(_d)
_s.close(); _d.close()
api.DB = 副本
assert api.DB == 副本 and api.DB != 真DB, "切库没生效 —— 下面会写真库"

print("纹样业务核定 · 检查")

待 = mr.待核的(副本)
if not 待:
    print("ℹ️ 副本里没有「待业务核」的商品 —— **这一轮没验**(不是验过了)")
    sys.exit(0)
靶 = 待[0]["spu"]
靶名 = 待[0]["商品名"]
print(f"  (拿「{靶名}」({靶}) 当靶子,库里还有 {len(待)} 件待核)")

# ── 覆盖层 ──────────────────────────────────────────────
w0, src0, _ = mr.定(靶, 靶名, db=副本)
ck("没核过的时候走推算,报「待业务核」", (w0, src0), (motif.待核, motif.待核))

# ── 写口的六道拦 ────────────────────────────────────────
api._ME.set(None)
ck("没登录 → 拒", "error" in api.review_motif(靶, "折枝", why="看了实物", said="这件是折枝"), True)

api._ME.set({"role": "顾问", "name": "测试顾问"})
r = api.review_motif(靶, "折枝", why="看了实物", said="这件是折枝")
ck("顾问身份 → 拒(要总部运营)", "error" in r and "总部运营" in r["error"], True)

api._ME.set({"role": "总部运营", "name": "测试运营"})
ck("why 空 → 拒", "error" in api.review_motif(靶, "折枝", why="", said="这件是折枝"), True)
ck("said 空 → 拒", "error" in api.review_motif(靶, "折枝", why="看了实物", said=""), True)
r = api.review_motif(靶, "折枝", why="看了实物", said="你帮我定一下这件")
ck("**原话里没出现那个纹样的说法 → 拒(模型不许替人猜)**",
   "error" in r and "没出现" in r["error"], True)
r = api.review_motif(靶, "缠枝莲花纹冰裂", why="看了实物", said="这件是缠枝莲花纹冰裂")
ck("词表外的纹样 → 拒(闭集)", "error" in r and "闭集" in r["error"], True)

# ── 正常核定 ────────────────────────────────────────────
r = api.review_motif(靶, "折枝", why="看了商品图,袖口和前襕都是单枝折花",
                     said="这件是折枝的")
ck("总部运营 + 齐全 → 写进去了", r.get("纹样"), "折枝")
ck("来源标成「业务核」", r.get("来源"), mr.来源)
ck("依据里带了是谁核的", "测试运营" in (r.get("依据") or ""), True)

w1, src1, ev1 = mr.定(靶, 靶名, db=副本)
ck("**核过之后 `定()` 返回核定值,不是推算值**", (w1, src1), ("折枝", mr.来源))
ck("核过的商品从「待业务核」清单里消失",
   靶 not in [x["spu"] for x in mr.待核的(副本)], True)

剩 = mr.待核的(副本)
if 剩:
    靶2 = 剩[0]["spu"]
    r = api.review_motif(靶2, "无纹样", why="看了实物,通身没有花", said="这件是素面的")
    ck("「这件确实是素面」能核成「无纹样」(素面说法也认)", r.get("纹样"), "无纹样")
    w2, src2, _ = mr.定(靶2, 剩[0]["商品名"], db=副本)
    ck("**「无纹样」和「待业务核」是两回事**(核成无纹样后不再是待核)",
       (w2 != motif.待核, src2), (True, mr.来源))

api._ME.set(None)
api.DB = 真DB

print(f"  (验了 {n} 条)")
if n == 0:
    print(f"{R}❌ 一条都没验{D}"); sys.exit(1)
if 坏:
    print(f"{R}❌ 纹样核定 {len(坏)} 条不过{D}"); sys.exit(1)
print(f"{G}✅ 纹样核定:核过的不被重算覆盖,写口六道拦全在"
      f"(含**原话校验** —— 模型替人猜的核不进去){D}")
