#!/usr/bin/env python3
"""工具使用评测集 —— 考的是「工具变多之后会不会用错」。

**为什么原来那 20 道题不够用:** 它们全是退款定因和客户合并,考的是「读了数据会不会推理」。
而这一路加到 19 个工具之后,新的失败模式完全不同:

  · **该调的没调** —— 报了数字却没查,答案看起来完全正常,只是数字是编的
  · **调错了工具** —— 问尺码去查了相容矩阵,答得头头是道但答非所问
  · **参数传错** —— 客户说「整幅」传成「局部」,成本和工期同时差四倍
  · **多调了不该调的** —— 每一次都是钱

**评测和体检不是一回事,不能互相替代:**
体检(guards)测「有没有违规」,是全量的、当场的;
评测测「答得对不对」,是抽样的、事后的。前者拦得住格式,拦不住答错。

三个轴一起打分:**轨迹(调对工具没)· 内容(结论对不对)· 体检(有没有违规)**。
三个都过才算过 —— 只看内容的话,一个瞎猜蒙对的答案会被判成满分。

锚点**全部从库里现算**,不写死。数据变了锚点跟着变,评测不会烂在原地。
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, os.path.join(HERE, "..", "agentsite"))
import api
import guards

# 「没」必须单列。第一版只写了「没法」,结果「**没**有现货」被判成说了「有现货」——
# 这个项目在否定上已经栽过第六次了,每次都是漏了某一种写法。
import textmatch as tm     # **中文否定与子串统一走这里** —— 原来四个文件各有一份词表,
                          # 每次踩坑只补一份,别的三份继续错(见 textmatch.py 文件头)

RE_THOUSAND = re.compile(r"(?<=\d),(?=\d{3})")


def _norm(t):
    """去掉数字里的千分位逗号。

    模型写「¥12,024.09」而锚点是「12024」—— 逗号一插,字符串匹配就断了。
    这类失败**看起来像模型答错,其实是判分器不认**,比真答错更难发现。
    """
    return RE_THOUSAND.sub("", t)


def hit(text, group, negation=False):
    """group 里任一个词出现就算命中。

    **must 类锚点不做否定检查,forbid 类才做**(negation=True):
      must  问「提到这个事实了吗」—— 一个数字不存在「被否定」这回事
      forbid 问「说了这句不该说的话吗」—— 被否定就不算说了
    """
    for src in (text, _norm(text)):
        w = tm.says(src, group) if negation else tm.mentions(src, group)
        if w: return w
    return None


# ── 锚点:全部现算 ──────────────────────────────────────────────────────
def A():
    d = {}
    d["m_waist"] = api.kb_size("PT04", "M")["尺码表"]["M"]["腰围"]
    d["bom_yj"] = api.kb_bom("PT04", "M", "云锦", ["盘金绣"])["物料成本"]
    d["bom_mm"] = api.kb_bom("PT04", "M", "棉麻", ["盘金绣"])["物料成本"]
    lead = api.kb_lead("PT06", "M", "云锦", ["缂丝"], "整幅", from_date="2026-09-04")
    d["lead_slow"], d["lead_fast"] = lead["最慢天数"], lead["最快天数"]
    dl = api.kb_lead("PT06", "M", "云锦", ["缂丝"], "整幅",
                     need_date="2026-10-01", from_date="2026-09-04")
    d["dl_ok"], d["dl_last"] = dl["赶得上"], dl["最晚下单日"]
    d["yj_lead"] = api.get_stock(material="云锦")["lead_days"]
    d["cap_neck"] = api.get_capacity(from_date="2026-09-04")["瓶颈工种"]
    kc = api.get_capacity("缂丝", 20, "2026-09-04")
    d["ks_wait"], d["ks_who"] = kc["排队等待天数"], kc["建议师傅"]
    d["combo_rule"] = api.kb_combo("妆花", "纱")["rule"]
    fit = api.kb_fit("C10013", "PT04")
    d["fit_grade"], d["fit_feat"] = fit["档位"], (fit.get("体型特征") or [""])[0]
    d["fit2_grade"] = api.kb_fit("C10001", "PT04")["档位"]
    oid = api._rows("SELECT id,status FROM ordr WHERE status<>'取消' LIMIT 1")[0]
    d["ord_id"], d["ord_st"] = oid["id"], oid["status"]
    d["af_n"] = api.get_aftersale(status="退款失败")["hit"]
    return d


# **跑评测之前先验锚点。**
# 这个文件里的锚点全是从库里现算的 —— 好处是数据变了跟着变、评测不会烂在原地,
# 代价是**实现错了锚点跟着错**(同源谬误)。
# pinned_check.py 里那 8 条是人从 md 手抄的、故意不现算,专门抓这个。
# 它们对不上就别跑了:**拿错的期望值跑一轮评测,比不跑更糟** ——
# 你会拿到一份看起来很正常的成绩单,然后照着它去改本来正确的提示词。
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
import pinned_check as _pin
_bad = _pin.verify()
if _bad:
    print("❌ 手抄锚点对不上,拒绝跑评测(先跑 knowledge/pinned_check.py 看是哪一条):",
          file=sys.stderr)
    for p, why in _bad: print(f"   · {p['name']}:{why}", file=sys.stderr)
    sys.exit(1)

K = A()

# need: 轨迹里必须出现的工具;must: 每组至少命中一个;forbid: 一个都不许(未被否定地)出现
CASES = [
 ("T01", "阔褶马面裙(PT05)有 S 码吗?", ["kb_pattern", "kb_size"],
  [("没有 S", "不做 S", "S 码没有", "裁不出", "不在", "只有 M")], ["可以订做 S", "S 码有货"]),
 ("T02", "PT04 明制马面裙·标准,M 码的成衣腰围是多少?", ["kb_size"],
  [(f"{K['m_waist']:g}",)], []),
 # ⚠️ 第二条期望原来写的是 `(K["fit_feat"],)` —— 而 C10013 **没有体型特征**,
 # 真值取出来是空串,于是这条期望永远满足不了,**白扣一条内容分**。
 # 真值为空就不该有这条期望;而「这位客户恰好没有体型特征」这件事
 # **本身会变**(换个客户、补一条体型记录就有了),所以按真值**现算**要不要带上,
 # 不写死 —— 和 `fit2_grade` 那条「别凭印象写期望」是同一个做法。
 ("T03", "客户 C10013 做 PT04 马面裙,推荐什么码?", ["kb_fit"],
  [(K["fit_grade"],)] + ([(K["fit_feat"],)] if (K["fit_feat"] or "").strip() else []),
  []),
 # 这条原本写的期望是「需补量」—— 而 C10001 的真值是「全定制」。
 # **用例写错比代码写错更难发现**,因为它会让你去改本来正确的东西。
 # 改成从库里现算,别再凭印象写期望。
 ("T04", "客户 C10001 做 PT04 马面裙,推荐什么码?说明判定依据。", ["kb_fit"],
  [(K["fit2_grade"],), ("关键尺寸", "差", "体型", "补量", "版师")], []),
 ("T05", "云锦做 PT04 马面裙 M 码配盘金绣,物料成本多少?", ["kb_bom"],
  [(f"{int(K['bom_yj'])}"[:4],), ("不是最终报价", "不含工时", "不是售价", "物料成本")], []),
 ("T06", "同一条 PT04 马面裙 M 码盘金绣,云锦和棉麻的物料成本差多少?", ["kb_bom"],
  [(f"{int(K['bom_yj'])}"[:4],), (f"{int(K['bom_mm'])}"[:3],)], []),
 ("T07", "为什么云锦做同一条裙子比棉麻用布多?", ["kb_bom", "kb_detail", "kb_lookup"],
  [("幅宽", "门幅")], []),
 ("T08", "PT06 立领长衫 M 码,云锦、缂丝整幅,要多久能拿到?", ["kb_lead"],
  [(f"{K['lead_slow']}",)], []),
 # 原本写的是「同上配置」—— 而**每道题都是全新会话,没有上文**。
 # 模型答不上来不是它的错,是用例默认了不存在的连续性。
 ("T09", "PT06 立领长衫 M 码、云锦、缂丝整幅,客户婚礼在 2026-10-01,"
         "今天 2026-09-04 下单来得及吗?", ["kb_lead"],
  [("赶不上", "来不及", "不够"), (K["dl_last"],)], ["来得及", "赶得上", "没问题"]),
 ("T10", "PT06 立领长衫云锦缂丝整幅这件,客户愿意加钱,能不能加急赶出来?",
  ["kb_lead", "get_capacity"],
  [("不能", "加不了", "无效", "没法", "只能等")], ["可以加急", "加钱可以赶", "能提前"]),
 ("T11", "云锦现在有现货吗?没有的话要备料多久?", ["get_stock"],
  [("无现货", "没有现货", "没现货"), (f"{K['yj_lead']}",)], ["有现货"]),
 ("T12", "工坊现在瓶颈在哪个工种?", ["get_capacity"],
  [(K["cap_neck"],)], []),
 ("T13", "缂丝这活现在什么时候能排上?今天是 2026-09-04。需要 20 工日。", ["get_capacity"],
  [(K["ks_who"],), ("加不了人", "只有一位", "一人一机", "加钱也没用", "插不了队")], []),
 ("T14", "数码印花这个工艺现在能接单吗?", ["get_capacity"],
  [("没有师傅", "产能缺口", "外发", "接不了")], ["可以安排", "排得上"]),
 ("T15", f"订单 {K['ord_id']} 现在到哪一步了?", ["get_order"],
  [(K["ord_st"],)], []),
 ("T16", "客户上周下的那单到哪一步了?", [],
  [("订单号", "单号", "客户号", "提供", "查不到", "无法定位")],
  ["已发货", "生产中", "已完成", "待发货"]),
 ("T17", "现在有几笔售后是「退款失败」状态?", ["get_aftersale"],
  [(f"{K['af_n']}",)], []),
 ("T18", "客户问她那笔售后退款的渠道流水在哪能查到?", ["get_aftersale"],
  [("外部", "售后/维保", "不在本系统", "这里查不到")], ["押金流水", "get_refund_trace 里有"]),
 ("T19", "妆花能用在纱上吗?", ["kb_combo"],
  [("不可", "做不了", "不能"), (K["combo_rule"], "织造阶段")], ["可以做", "没问题"]),
 ("T20", "灰缬能做在浅色棉麻上吗?", ["kb_combo"],
  [("不可", "做不了", "不行"), ("深", "拔染", "白花")], ["可以", "没问题"]),
 ("T21", "客户要在香云纱上做妆花,她很急,加钱能不能赶出来?", ["kb_combo"],
  [("不可", "做不了", "物理"), ("加钱", "不是钱", "赶不出来", "工期")],
  ["可以加急", "加钱可以做"]),
 ("T22", "云锦 PT04 马面裙 M 码盘金绣,这件卖多少钱?给客户报个价。", ["kb_bom"],
  [("物料成本", "不是最终报价", "不含工时"), ("店长", "财务", "定价")], []),
 ("T23", "客户要整幅缂丝的 PT06 立领长衫 M 码云锦,大概多少钱?", ["kb_bom"],
  [("整幅",)], []),
 # 锚点第一版只写了三个词,而模型说的是「请顾问给我这些」—— 一个词都没撞上。
 # **锚点要按意思找同义词,不能凭第一反应写三个就完事。**
 # 第二组要求它真的点出缺了哪些参数,比单纯匹配「要信息」的措辞可靠。
 ("T24", "给客户出份报价单。", [],
  [("需要", "提供", "还差", "先告诉我", "哪些", "给我", "请顾问", "补充", "问全", "才能"),
   ("客户", "形制", "面料", "工艺", "尺码")], ["物料成本合计", "免责声明"]),
]


def judge(cid, text, traj, guard_violations=None):
    """三轴打分。纯函数,离线可测。"""
    c = next(x for x in CASES if x[0] == cid)
    _, q, need, must, forbid = c
    bad = []
    names = " ".join(t.split("__")[-1] for t in traj)
    if need and not any(n in names for n in need):
        bad.append(f"轨迹:该调 {need} 里的工具,实际调了 [{names or '无'}]")
    if not need and traj:
        pass                       # 不要求工具的题,调了也不扣分(可能是为了确认)
    for g in must:
        # ⚠️ **真值为空时不许生成期望。**
        # T03 的期望来自 `(fit.get("体型特征") or [""])[0]` —— 这位客户
        # 没有体型特征,真值是 `''`,而用例照样造了一条「回答里必须出现 ''」。
        # 空期望有两种坏法,都得防:
        #   **永远失败** —— T03 就是这样,一条内容分白扣
        #   **静默变成永远通过** —— 那更糟,一条判据消失了而成绩单还是满分
        # 所以这里**不是悄悄跳过**,是当场报出来:期望该修,不该假装它不存在。
        # (「分母为零不给比率,给一句话」——期望值也一样。)
        if not [x for x in g if (x or "").strip()]:
            bad.append(f"用例本身有问题:这条期望是**空的**"
                       f"(真值取出来是空串)—— 空期望要么永远失败、"
                       f"要么静默变成永远通过,**两种都不该留着**")
            continue
        if not hit(text, g):
            bad.append(f"内容:没提到 {g[0]}(同义:{'/'.join(g[1:]) or '无'})")
    for w in forbid:
        if hit(text, (w,), negation=True):
            bad.append(f"内容:出现了禁止说法「{w}」")
    for v in (guard_violations or []):
        bad.append(f"体检:{v['check']} {v['msg'][:40]}")
    return (not bad), bad


# ── 跑评测(要花钱,不进 check.sh)────────────────────────────────────
if __name__ == "__main__":
    import asyncio, json, time
    only = [a for a in sys.argv[1:] if a.startswith("T")]
    todo = [c for c in CASES if not only or c[0] in only]
    import sdk
    print(f"工具使用评测 · {len(todo)} 题 · 模型 {os.environ.get('DEEPSEEK_MODEL','deepseek-v4-pro')}")
    print("=" * 100)
    ok_n, cost, rows = 0, 0.0, []
    for cid, q, need, must, forbid in todo:
        t0 = time.time()
        try:
            r = asyncio.run(sdk.run("kb", q, max_turns=14))
        except Exception as e:
            rows.append((cid, False, [f"跑挂了:{type(e).__name__}: {e}"], "", 0, "", {}, 0, [])); continue
        names = [t["tool"] for t in r["trajectory"]]
        ok, why = judge(cid, r["text"], names, r.get("guard_violations"))
        ok_n += ok; cost += r.get("cost_usd") or 0
        rows.append((cid, ok, why, ",".join(n.split("__")[-1] for n in names),
                     r.get("cost_usd") or 0, r["text"], r.get("usage") or {},
                     r.get("answer_turns"), r.get("guard_violations") or []))
        print(f"[{cid}] {'✅' if ok else '❌'} {q[:34]:36s} "
              f"{len(names)}调 {time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}  "
              f"{'' if ok else why[0][:52]}")
        for w in (why[1:] if not ok else []): print(f"        {w[:88]}")
    print("=" * 100)
    print(f"通过 {ok_n}/{len(todo)} = {ok_n/max(len(todo),1)*100:.0f}%  |  总花费 ${cost:.4f}")
    out = os.path.join(HERE, "..", ".feynman", "tool-eval.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # **存答案原文。** 不存的话,失败了只能重跑才知道它到底说了什么 ——
    # 而重跑要花钱,还不一定复现。和 triage 存 ai_text 是同一个理由。
    json.dump([dict(case=c, passed=o, why=w, tools=t, cost=k, text=x,
                    usage=u, turns=n2, guard=g) for c, o, w, t, k, x, u, n2, g in rows],
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
