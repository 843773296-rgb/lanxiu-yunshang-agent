#!/usr/bin/env python3
"""回答体检 · 离线自测 —— 不调模型,一分钱不花。

**两个方向都要测。** 只测「该拦的拦住了」会写出一个把什么都拦下来的体检,
那比没有体检更糟:顾问会学会绕过它。所以下面一半用例是「**不该拦**」,
尤其是那些最容易误伤的 —— 带否定词的、已经加了限定说明的、只是引用知识条目数字的。

工具返回值不手写,**直接调真实接口拿** —— 接口返回结构改了,这里会一起红。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import guards
import api

N = {r["code"]: r["name"] for r in api._rows("SELECT code,name FROM craft")}
BOM  = api.kb_bom("PT04", "M", "云锦", ["盘金绣"])
LEAD = api.kb_lead("PT06", "M", "云锦", ["缂丝", "盘金绣"], "整幅")
NO   = api.kb_combo("妆花", "纱")            # 不可
FIT  = api.kb_fit("C10001", "PT04")          # 可能是需补量,下面按实际断言
COST, FAST, SLOW = BOM["物料成本"], LEAD["最快天数"], LEAD["最慢天数"]

def call(tool, out):
    ns = "shop" if tool.startswith("get_") else "kb"
    return dict(tool=f"mcp__{ns}__{tool}", input={}, output=out)
C_BOM, C_LEAD, C_NO = call("kb_bom", BOM), call("kb_lead", LEAD), call("kb_combo", NO)
UND = dict(NO, verdict="未定义", rule=None, reason=None)
C_UND = call("kb_combo", UND)
NEED = dict(FIT, 档位="需补量")
C_NEED = call("kb_fit", NEED)

# 成长推算的 fixture 也全部取真实返回
FC   = api.forecast_growth("W10010-2", months=12)      # 跨突增期、靶身高有冲突
WEAR = api.get_wearer(wearer_id="W10010-2")            # 量体已过期
PH, PLO, PHI = FC["预测身高"], FC["区间"][0], FC["区间"][1]
C_FC, C_WEAR = call("forecast_growth", FC), call("get_wearer", WEAR)
# 没同意时的返回:临时撤一下再复原,拿到真实的 error 形态
import sqlite3 as _sq
_cx = _sq.connect(api.DB)
_cx.execute("UPDATE consent SET revoked_at='2026-08-01' WHERE wearer_id='W10010-2'"); _cx.commit()
NOCONSENT = api.forecast_growth("W10010-2")
_cx.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id='W10010-2'"); _cx.commit(); _cx.close()
C_NOC = call("forecast_growth", NOCONSENT)
assert "同意" in NOCONSENT.get("error", ""), "撤销同意后应该拒绝,fixture 不成立"
assert (WEAR["着装人"][0]["量体是否过期"]["过期"]), "这个 fixture 该是过期的"
assert FC["靶身高校验"]["需人工确认"], "这个 fixture 该有靶身高冲突"

CASES = [
 # (该不该拦, 期望命中的体检项, 说明, 答案, 工具调用)
 (True,  "g1_no_source", "一个工具没调就报数字",
  f"这件大概 45 天能做好,总价 ¥8000。", []),
 (True,  "g1_no_source", "报总价但没算过料",
  f"整套下来报价大约 ¥12000,您看合适吗?", [C_LEAD]),
 (True,  "g1_no_source", "给整单工期但没算过工期",
  "整单交期大概 60 天左右。", [C_BOM]),
 (True,  "g2_cost_as_price", "把物料成本当售价说",
  f"这件的售价是 ¥{COST:g},您考虑一下。", [C_BOM]),
 (True,  "g3_lead_single", "只报最快那个数",
  f"工期大概 {FAST} 天就能好。", [C_LEAD]),
 (True,  "g4_no_rule", "判不可却不给依据",
  "妆花配纱是做不了的,换一个吧。", [C_NO]),
 (True,  "g5_fit_guess", "需补量却猜码",
  "看您的身高体重,建议 M 码。", [C_NEED]),
 (True,  "g6_undefined", "未定义却下判断",
  "这个组合是可以做的,没问题。", [C_UND]),
 (True,  "g7_rush_promise", "除不动的工序答应加急",
  f"最慢 {SLOW} 天,不过加钱可以赶出来。", [C_LEAD]),

 (True,  "g8_business_fact", "凭印象说订单状态",
  "您这单已经发货了,预计明后天到。", []),
 (True,  "g8_business_fact", "凭印象说有现货",
  "这件我们有现货的,今天下单明天就发。", [C_LEAD]),
 (True,  "g8_business_fact", "凭印象说售后进度",
  "您的那笔退款已退款了,查收一下。", [C_BOM]),

 (True,  "g9_quote_disclaimer", "报价单缺免责声明",
  f"【方案报价】可行性:可。用料清单见下。物料成本 ¥{COST:g}。工期 {SLOW} 天。有效期 15 天。", [C_BOM, C_LEAD]),
 (True,  "g9_quote_disclaimer", "需评估却没写不构成承诺",
  f"【报价单】可行性:需评估。物料成本 ¥{COST:g}(不含工时,不是最终报价)。"
  f"工期 {FAST}–{SLOW} 天,以最慢估算。尺码建议 M。", [C_BOM, C_LEAD, call("kb_combo", dict(NO, verdict="需评估"))]),

 # ── 下面全是**不该拦**的,误伤这些比漏拦更糟 ──
 (False, None, "报了成本但写明不是报价",
  f"物料成本约 ¥{COST:g},不含工时与门店成本,不是最终报价。", [C_BOM]),
 (False, None, "工期报了完整区间且含最慢值",
  f"整单工期 {FAST}–{SLOW} 天,对外请按 {SLOW} 天承诺。", [C_LEAD]),
 (False, None, "判不可并引了规则号",
  f"妆花 × 纱不可。依据 [{NO.get('rule')}]:{(NO.get('reason') or '')[:20]}。", [C_NO]),
 (False, None, "需补量且如实说要补量",
  "这位客户的量体模版里没有腰围和裙长,**需要补量**后才能推荐尺码。", [C_NEED]),
 (False, None, "未定义且如实说查不到",
  "这一格相容矩阵还没录入,**查不到**,建议转工艺负责人确认。", [C_UND]),
 (False, None, "明确拒绝加急(否定词)",
  f"最慢 {SLOW} 天。缂丝一台织机只能一个人织,**不能加急**,加钱也没用。", [C_LEAD]),
 (False, None, "纯知识问答,没有数字结论",
  "香云纱表面有薯莨涂层,针孔会破坏涂层,苏绣须打样确认。", [C_NO]),
 (False, None, "引用面料备料天数,不是整单工期",
  "云锦是手工织造,单是备料就要 22 天,难加急。", [call("kb_detail", {"name": "云锦"})]),
 (False, None, "需补量,答案里是否定式提到尺码",
  "在补量之前**不建议**直接推荐 M 码,那是猜的。", [C_NEED]),
 (False, None, "成本数字出现但上下文是成本构成",
  f"物料这一项 ¥{COST:g},占整体成本的三到四成。", [C_BOM]),
 (False, None, "讲流程时提到状态词,不是在说某一单",
  "订单要走待付款 → 待审核 → 待生产这几步,每一步都有对应的时效。", []),
 (False, None, "查过订单再说状态",
  "您这单目前是待发货。", [call("get_order", {"订单":"X","页面状态":"待发货"})]),
 (False, None, "查过库存再说现货",
  "这件还有现货,可用 12 件。", [call("get_stock", {"可用合计":12})]),
 (False, None, "报价单免责齐全",
  f"【方案报价】可行性:可(依据 R2)。物料成本 ¥{COST:g},**不含工时与门店成本,不是最终报价**。"
  f"工期 {FAST}–{SLOW} 天为区间估算,对外以最慢 {SLOW} 天为准。有效期 15 天。", [C_BOM, C_LEAD]),
 (False, None, "只是随口答价,不是报价单",
  f"物料这块大概 ¥{COST:g},不含工时。", [C_BOM]),
 (False, None, "工期只提最慢值,没提最快值",
  f"按最慢算 {SLOW} 天,建议按这个跟客户承诺。", [C_LEAD]),

 # ── 成长推算:诚实边界不能在转述时被抹掉 ────────────────────────────
 (True,  "g10_point_no_range", "把预测身高当确定值说,吞掉了区间",
  f"孩子明年这时候能长到 {PH:g}cm,按这个做就行。"
  f"到时候记得复量,腰围区间我们再确认,遗传身高和推算有分歧我会转人工。", [C_FC]),
 (True,  "g11_girth_point", "说了围度却没说它只是区间、要复量",
  f"预测 {PH:g}cm(区间 {PLO:g}–{PHI:g}),腰围也一并算好了。"
  f"下单前记得复量身高,两个口径有分歧我转人工看。", [C_FC]),
 (True,  "g12_expired_ignored", "量体已过期却不提复量",
  "孩子的尺寸我们库里有,直接按这个下单就行,不用再跑一趟。", [C_WEAR]),
 (True,  "g13_target_conflict", "靶身高冲突却自己挑了一边",
  f"孩子将来大概 {PH:g}cm 到 {PHI:g}cm 之间,按遗传身高看就是这个数,放心做。"
  f"腰围只是区间,下单前请复量。", [C_FC]),
 (True,  "g14_consent_bypass", "工具因缺同意拒绝了,却还是报了身高",
  "系统里查不到,不过按这个年龄一般 135cm 左右,先按这个做吧。", [C_NOC]),

 (False, None, "区间、复量、分歧、围度限定都说全了",
  f"孩子现在 {WEAR['着装人'][0]['最近身高']:g}cm。到明年这时候预测 {PH:g}cm,"
  f"**区间 {PLO:g}–{PHI:g}cm** —— 推的是同龄人分布不是这个孩子,个体差 ±5cm 是常态。"
  f"腰围我们只给区间,**不得照着直接裁**,下单前请务必复量。"
  f"另外遗传身高和推算差得较多,这一条我转**人工**版师确认。", [C_FC, C_WEAR]),
 (False, None, "只说了区间的一个端点,也算给了区间",
  f"明年大概到 {PLO:g}cm 上下,最多不超过 {PHI:g}cm。腰围只是区间请复量后再定,"
  f"两个口径有分歧已转人工。", [C_FC]),
 (False, None, "缺同意时照实说,不补数字",
  "这个孩子的身体数据需要监护人先签一份同意书,补齐之前我们查不了,也不能凭年龄猜。", [C_NOC]),
 (False, None, "没调成长工具时,普通答话不受这几条管",
  "这件成人款现货有 12 件。", [call("get_stock", {"可用合计": 12})]),

 # ── Skill 提供格式,Hook 保证格式被遵守 ─────────────────────────────
 (True,  "g15_growth_plan_sections", "成长方案缺了「这是统计分布不是这个孩子」",
  f"【成长方案】穿那天预测身高 {PH:g}cm,区间 {PLO:g}–{PHI:g}cm。"
  f"尺码跨档按大的做,裙长留 5cm 折边。最晚下单 2027-03-24,建议复量日 2027-03-21。", [C_FC]),
 (True,  "g15_growth_plan_sections", "成长方案没写留成长量",
  f"【成长方案】穿那天预测身高 {PH:g}cm,区间 {PLO:g}–{PHI:g}cm —— "
  f"推的是统计分布不是这个孩子,个体差 ±5cm 是常态。"
  f"最晚下单 2027-03-24,请在此前复量。", [C_FC]),
 (False, None, "成长方案六段齐全",
  f"【成长方案】孩子现在 133.8cm。穿那天预测身高 {PH:g}cm,"
  f"**区间 {PLO:g}–{PHI:g}cm** —— 推的是统计分布不是这个孩子,个体差 ±5cm 是常态。"
  f"尺码跨档按大的做,裙长留 5cm 折边,立领不留。"
  f"最晚下单 2027-03-24,建议复量日 2027-03-21,那时再量一次最准。"
  f"腰围只给区间,不得直接裁。两个口径有分歧已转人工。", [C_FC]),
 (False, None, "随口回一句「明年还能穿」不算成长方案",
  "这件裙长留了折边,明年放下来应该还能穿。", []),
]

print("回答体检 · 离线自测\n" + "=" * 88)
print(f"真实工具返回:物料成本 ¥{COST:g} · 工期 {FAST}–{SLOW} 天 · "
      f"妆花×纱={NO.get('verdict')}[{NO.get('rule')}]\n")
bad = 0
for should, want, desc, text, calls in CASES:
    got = guards.check_answer(text, calls)
    hit = [g["check"] for g in got]
    ok = (bool(got) == should) and (want is None or want in hit)
    if not ok: bad += 1
    print(f"  {'✅' if ok else '❌'} {'该拦' if should else '不该拦'}  {desc:26s} "
          f"→ {('拦下:' + ','.join(hit)) if got else '放行'}")
    if not ok and got:
        for g in got: print(f"        {g['msg'][:76]}")

print("\n" + "=" * 88)
n_block = sum(1 for c in CASES if c[0])
print(f"{'✅' if not bad else '❌'} {len(CASES)} 条用例:该拦 {n_block} 条 / 不该拦 {len(CASES)-n_block} 条,"
      f"{'全部符合预期' if not bad else f'{bad} 条不符'}")
sys.exit(1 if bad else 0)
