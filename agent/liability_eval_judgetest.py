#!/usr/bin/env python3
"""售后判责判分器的对照自测 —— 不调模型,一分钱不花。

**这一轮判分器自己错了三次**(成长评测一次、识图评测两次),而且都是同一族:
查的是「提到没提到那个词」,该查的是「做了没做那件事」。
所以这次**先写对照用例,再跑模型** —— 便宜的错先抓掉。

两个方向都测:该过的必须过,该挂的必须挂。
判分器太松 → 满分成绩单是假的;太严 → 你会去改本来正确的提示词。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import liability_eval as L

BY = {c["root_cause"]: c for c in L.CASES}
CRAFT = BY["工艺瑕疵 · 我方免费返修"]
FULL = BY["尺寸偏差 · 记录完整 · 客方收费改"]
THIN = BY["尺寸偏差 · 记录不全 · 我方免费改"]
NOTIFIED = BY["特性类已告知 · 无责解释"]
UNNOTIFIED = BY["特性类未告知 · 我方让步"]
T = lambda *x: [f"mcp__shop__{k}" if k.startswith("get_") else f"mcp__kb__{k}" for k in x]
SITE = T("get_maintain", "kb_tables")

# (该不该过, 用例, 说明, 假答案, 轨迹, 体检)
CASES = [
 # ── 轨迹轴:判据藏在现场里 ────────────────────────────────────────────
 (False, CRAFT, "没查现场就下判责结论",
  "盘扣脱线属工艺瑕疵,我方责任,免费返修。", T("kb_tables"), []),
 (True,  CRAFT, "查了现场也查了判定表",
  "盘扣脱线属工艺瑕疵,我方责任,免费返修。", SITE, []),

 # ── 责任方轴 ──────────────────────────────────────────────────────────
 (False, CRAFT, "责任方说反了(说成客方)",
  "盘扣脱线是客户使用不当,客方责任,收费修。", SITE, []),
 (False, UNNOTIFIED, "该我方让步却判成无责",
  "面料起球属正常特性,无责,只做解释和保养。交付告知已说明。", SITE, []),
 (True,  UNNOTIFIED, "无签收 → 我方让步",
  "面料起球属特性类,但**没有交付告知签收记录**,按第五节末行:"
  "我方责任,让步处理。", SITE, []),
 (True,  NOTIFIED, "有签收 → 无责",
  "染色不均属特性类,交付时已书面告知并签收,故无责 —— 提供保养服务与解释。",
  SITE, []),

 # ── 依据轴:光给结论不算 ──────────────────────────────────────────────
 (False, THIN, "结论对但一句依据都没给",
  "我方责任,免费改。", SITE, []),
 (True,  THIN, "结论 + 依据(量体记录不全)",
  "客户没有量体记录,记录不全 → 我方责任,免费改。", SITE, []),
 # (「远程量体 → 按合同分担」两条对照 09-22 删了:业务定不准远程量体,判责表那一行已删)
 (True,  FULL, "到店且记录完整 → 客方收费改",
  "量体记录完整且相符(到店量体 5 项),客方责任,收费改。", SITE, []),

 # ── 金额轴:赔多少是人定的 ────────────────────────────────────────────
 (False, UNNOTIFIED, "编了具体赔付金额",
  "没有告知签收,我方让步 —— 建议补偿 500 元。", SITE, []),
 (True,  UNNOTIFIED, "让步但不报数",
  "没有交付告知签收,我方让步处理,具体补偿方案请店长确定。", SITE, []),

 # ── 体检轴 ────────────────────────────────────────────────────────────
 (False, CRAFT, "内容都对但体检打回了",
  "盘扣脱线属工艺瑕疵,我方责任,免费返修。", SITE,
  [{"check": "g17_liability_promise", "msg": "判责结论没写明须人工确认"}]),
]

if __name__ == "__main__":
    print("售后判责判分器 · 对照自测(不调模型)\n" + "=" * 96)
    bad = 0
    for should, case, desc, text, traj, guard in CASES:
        ok, why = L.judge(case, text, traj, guard)
        good = (ok == should); bad += not good
        print(f"  {'✅' if good else '❌'} {'该过' if should else '该挂'}  {desc:30s} "
              f"→ {'判过' if ok else '判挂'}")
        if not good:
            for w in why[:2]: print(f"        {w[:88]}")
    print("\n" + "=" * 96)
    n = sum(1 for c in CASES if c[0])
    print(f"{'✅' if not bad else '❌'} {len(CASES)} 条对照:该过 {n} / 该挂 {len(CASES)-n},"
          f"{'全部符合预期' if not bad else f'{bad} 条不符'}")
    print("  **先写对照再跑模型** —— 判分器的错比模型的错便宜得多,也好抓得多。")
    sys.exit(1 if bad else 0)

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「没查现场」那一轴关掉(不查现场也算过)',
     '没查现场就下判责结论'),
]
