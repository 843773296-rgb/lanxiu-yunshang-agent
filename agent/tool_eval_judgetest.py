#!/usr/bin/env python3
"""工具评测的**判分器自测** —— 不调模型,一分钱不花。

判分器自己也会错,而判分器错了比模型错更糟:**它会把对的判成错、错的判成对,
然后所有基于评测的结论都跟着歪,而且没人会去怀疑判分器。**

所以每条用例都造一对答案:一个**该过**、一个**该挂**,两个方向都测。
特别要测否定 —— 这个项目在否定上栽过五次(四次把否定当肯定,一次把转折当否定)。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tool_eval as te

K = te.K
T = lambda *xs: [f"mcp__kb__{x}" if not x.startswith("get_") else f"mcp__shop__{x}" for x in xs]

# (用例号, 该不该过, 说明, 答案, 轨迹, 体检违规)
# 注意 T11 那对:「**无**现货,需备料 22 天」—— 前面有个「无」,后面的 22 是要命中的锚点。
# must 若做否定检查,这个 22 会被误判成「被否定」。这一对就是为了钉住那个 bug。
CASES = [
 ("T01", True,  "查了版型并说清没有 S 码",
  "PT05 阔褶马面裙**没有 S 码**,尺码序列只有 M/L/XL —— 褶量在 S 码上排不开,是版型裁不出来,不是缺货。",
  T("kb_pattern"), None),
 # ↓ 真跑原话(2026-09-15,Claude)。**它答对了,而旧判据判它挂** ——
 #   词表里是「只有 M」,而答案写的是「只有 **M、L、XL**」,被 markdown 加粗打断。
 ("T01", True,  "真跑原话:答了「没有」,并推荐了有 S 码的替代版型",
  "**没有。** PT05(明制马面裙·阔褶)只有 **M、L、XL** 三个尺码。"
  "如果顾客需要更小的尺寸,可以考虑 **PT04**(明制马面裙·标准)—— 它有 S 码,但褶量较小。",
  T("kb_pattern"), None),
 ("T01", False, "说成缺货,还说可以订",
  "PT05 目前 S 码有货紧张,可以订做 S 码,大概两周。", T("kb_pattern"), None),

 # ↓ 这两条钉的是**判据自己犯过的两个错**,方向相反:
 #   ① 「有 S 码」四个字出现在**推荐替代版型**的句子里 —— 不算违规(上面那条)
 #   ② 「没有 S 码」里含着「有 S 码」 —— 中文否定坑第八次,而且是在修同类 bug 时犯的
 ("T01", True,  "「没有 S 码」里含着「有 S 码」,不许被当成声称",
  "PT05 阔褶马面裙**没有 S 码**,尺码序列只有 M/L/XL。", T("kb_pattern"), None),

 ("T02", True,  "查了尺码表并给出数值",
  f"PT04 的 M 码成衣腰围是 {K['m_waist']:g} cm(成衣尺寸,不是人体尺寸)。", T("kb_size"), None),
 ("T02", False, "没查就报数",
  "M 码腰围一般是 70 cm 左右。", [], None),

 ("T04", True,  "给出档位并说明依据",
  f"客户 C10001 判为**{K['fit2_grade']}**:关键尺寸差值超出调号范围,须版师出专属版。",
  T("kb_fit"), None),
 ("T04", False, "没说档位也没说依据",
  "看数据穿 M 码应该没问题。", T("kb_fit"), None),

 ("T09", True,  "算了倒推并如实说赶不上",
  f"**赶不上**。按最慢工期算,最晚下单日是 {K['dl_last']},现在已经过了。建议改配置或改期。",
  T("kb_lead"), None),
 ("T09", False, "说来得及",
  f"来得及,最晚 {K['dl_last']} 下单就行,现在下没问题。", T("kb_lead"), None),

 ("T10", True,  "明确拒绝加急",
  "缂丝**不能**加急 —— 一台织机只能一个人织,加人无效,加钱也没用。", T("kb_lead"), None),
 ("T10", False, "答应了加急",
  "可以加急,我们安排两位师傅并行,能提前十天左右。", T("kb_lead"), None),

 ("T11", True,  "查了现货并给出备料天数",
  f"云锦**无现货**,需备料 {K['yj_lead']} 天。", T("get_stock"), None),
 ("T11", False, "凭印象说有现货",
  "云锦有现货的,随时能开工。", T("get_stock"), None),

 ("T16", True,  "没有单号就要单号,不编状态",
  "查不到「上周那单」—— 请提供订单号或客户号,我再去查。", [], None),
 ("T16", False, "没查就编了个状态",
  "您那单已发货了,预计两天到。", [], None),

 ("T19", True,  "判不可并给依据",
  f"妆花**不可**用于纱。依据 [{K['combo_rule']}]:妆花是织造技法,须在织造阶段完成。",
  T("kb_combo"), None),
 ("T19", False, "说可以做",
  "妆花可以做在纱上,效果还不错。", T("kb_combo"), None),

 ("T22", True,  "只给成本,把定价交回去",
  "物料成本约 ¥12024,**不含工时与门店成本,不是最终报价**;最终售价由店长按定价系数出。",
  T("kb_bom"), None),
 ("T22", False, "直接当售价报出去",
  "这件卖 ¥12024,可以给客户报这个数。", T("kb_bom"), None),

 # ── 否定保护:禁止说法被否定了,不该扣分 ──
 ("T10", True,  "禁止词出现但被否定了(不可以加急)",
  "**不可以加急**,缂丝一人一机,加钱也没用,只能等。", T("kb_lead"), None),
 ("T16", True,  "禁止词出现但是在说「不能说已发货」",
  "在查到之前我不能说它已发货 —— 请给我订单号。", [], None),

 # ── 体检违规要计入 ──
 ("T05", False, "内容都对,但体检报了违规",
  f"物料成本 ¥{int(K['bom_yj'])},不含工时,不是最终报价。", T("kb_bom"),
  [{"check": "g2_cost_as_price", "msg": "把物料成本当售价说了"}]),
]

print("工具评测 · 判分器自测\n" + "=" * 86)
bad = 0
for cid, should, desc, text, traj, gv in CASES:
    ok, why = te.judge(cid, text, traj, gv)
    good = (ok == should)
    if not good: bad += 1
    print(f"  {'✅' if good else '❌'} {cid} {'该过' if should else '该挂':4s} {desc:30s} "
          f"→ {'过' if ok else '挂:' + why[0][:44] if why else '挂'}")
    if not good and why:
        for w in why: print(f"        {w}")

print("\n" + "=" * 86)
n_pass = sum(1 for c in CASES if c[1])
print(f"{'✅' if not bad else '❌'} {len(CASES)} 对照用例:该过 {n_pass} / 该挂 {len(CASES)-n_pass},"
      f"{'全部符合预期' if not bad else f'{bad} 条不符'}")
sys.exit(1 if bad else 0)
