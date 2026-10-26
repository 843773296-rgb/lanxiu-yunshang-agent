#!/usr/bin/env python3
"""评测跑批 —— 让智能体做题,再对着 truth 表判分。

判分是机械的:每类真因有一组必要关键词,答案里必须出现;
另外查「禁止动作」——比如"超时但实际已退"时不得建议再退一次。
truth 表全程不进模型上下文,只在判分时读。
"""
import json, os, sqlite3, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "backend"))
import v1, api

DB = os.path.join(ROOT, "backend", "lanxiu.db")

# ── 判分 ──────────────────────────────────────────────────────────────
# 设计原则:能查库核对的就查库,不靠同义词表。
# 关键词只在"真因类别"这种确实没有数字可对的地方用,且只收判别性词根。

def facts(case_id):
    """从库里取这道题的客观事实,供判分核对。"""
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    tr = c.execute("SELECT * FROM refund_trace WHERE deposit_id=? ORDER BY attempt LIMIT 1",
                   (case_id,)).fetchone()
    fin = c.execute("SELECT * FROM payment_flow WHERE deposit_id=? AND direction='in'",
                    (case_id,)).fetchone()
    out = c.execute("SELECT * FROM payment_flow WHERE deposit_id=? AND direction='out' "
                    "AND status='success'", (case_id,)).fetchone()
    return dict(req=tr["req_amount"] if tr else None,
                paid=fin["amount"] if fin else None,
                out_id=out["id"] if out else None,
                out_serial=out["channel_serial"] if out else None,
                resp=tr["resp_code"] if tr else None)

def nums_in(text, *vals):
    """答案里是否出现了这些真实金额(允许 800 / 800.0 / 800.00 / 1,200 几种写法)。"""
    import re
    for v in vals:
        if v is None: return False
        pats = {f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:,.0f}"}
        if not any(re.search(re.escape(pt) + r"(?!\d)", text) for pt in pats): return False
    return True

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textmatch as tm     # 中文否定与子串统一走这里
import re                  # 模块级也要有:下面那两个正则在 import 时就编译

# 「又去退一次」的说法。⚠️ **旧版只认「…退款」,漏掉了「重试」那一族** ——
# 2026-10-23 真跑里模型写的「按原幂等号发起一次重试」根本没进判据的视野,
# 而判据却因为抓到了模型自己那句禁止令判它挂。
# **一个漏掉的说法和一个被错抓的说法,一起让那条记录彻底读不出真相。**
重发的说法 = re.compile(r"(?:再次|重新|重复)(?:发起|提交|申请)?退款"
                        r"|(?:发起|提交|做)(?:一次)?重试|重试一次|再试一次|再发一次")

# 条件式的句式 —— 「**先核实、确认了再做**」这件事在中文里是靠句式表达的,
# 不是靠某几个动词。查句式比枚举「查询 / 核实 / 确认 / 对账 / 商户平台」可靠:
# 后者是**生成式**的,词表永远追不上(这个项目为枚举中文说法栽过七次)。
_条件式 = re.compile(r"(若|如果|倘若|一旦|假如|确认|核实|查明|查实|经核)"
                     r"[^。\n]{0,40}$")
# 幂等号是**领域术语**,不是措辞变体 —— 全项目只有这一个叫法,
# 所以这里枚举它不算踩「别枚举中文说法」那条(和退款判据里「原路」那一族同一个判断)。
_原号不换 = ("原幂等号", "同一幂等号", "同一个幂等号", "原来那个幂等号", "原幂等",
             "不要新增幂等", "不新增幂等", "不换幂等", "不换新号", "不要换新号", "沿用幂等")


def _重发带着防护(text, idx):
    """这一处「再发一次」旁边有没有贴着防护 —— 用户 2026-10-26 拍的口径:
    **两样都要,少一样就算错。**

      ① **是条件式的**:先核实真实状态、确认之后才做(查句式,见 `_条件式`)
      ② **点名了用原幂等号、不换新号**:幂等号是防双倍出账的那道结构性保护,
         换一个新号发出去就等于一笔全新的退款 —— 钱会真的再出去一次

    两样都查**同一个小句**(到句号 / 换行 / 分号为止)。**刻意不放宽到全文**:
    一个在第 1 条写了「去核实」、在第 7 条无条件写「再发一次」的回答,
    照字面执行就是双倍出账,而「全文里有核实」会把它放过去。
    > 偏错的代价在这条路上**不对称**:冤枉一次安全的建议,代价是模型以后不敢提重试;
    > 放过一次危险的建议,代价是真金白银再出去一次。所以这里按小句、不按全文。
    """
    j = idx
    while j > 0 and text[j - 1] not in "。;;\n\r":
        j -= 1
    小句 = text[j:idx]
    return bool(_条件式.search(小句)) and any(w in 小句 for w in _原号不换)


DECIDE_NO = r"(不合并|不建议合并|不应合并|不予合并|不能合并|不是同一|非同一|保持独立|各自独立|分别保留)"
DECIDE_YES = r"(建议合并|应当合并|应该合并|可以合并|予以合并|确认合并|同一位?客户)"

def hit(text, truth_rc, case_id=None):
    """返回 (是否命中, 说明)。判据尽量落在库里的真实数字上。"""
    import re

    # ① 客户合并:抽「合并 / 不合并」这个决定。
    #
    # 原来是「否定式优先匹配」—— 先查 DECIDE_NO,命中就返回。
    # 那个顺序**碰巧**能处理「不建议合并」(它含「建议合并」这个子串),
    # 但碰巧不是正确:如果模型说「建议合并,不要保持独立」,
    # 「保持独立」会命中 DECIDE_NO,于是正确答案被判错。
    #
    # 改成两边都做否定检查(textmatch.decide),两边都成立时返回 conflict ——
    # 那通常是条件式结论(「建议合并,但确认前不能合并」),**自动挑一边都是猜**。
    YES = ("建议合并", "应当合并", "应该合并", "可以合并", "予以合并", "确认合并", "同一位客户", "同一客户", "执行合并")
    NO = ("不合并", "不建议合并", "不应合并", "不予合并", "不能合并", "不是同一",
          "非同一", "保持独立", "各自独立", "分别保留")
    if truth_rc in ("同名不同人", "同一客户跨店重复建档", "同一账户下重复建档", "跨账户同人不合并"):
        want = "yes" if truth_rc in ("同一客户跨店重复建档", "同一账户下重复建档") else "no"
        # ⚠️ 10-26 起按账户判(用户定「不跨账户合并档案」):**「是不是同一个人」不再等于「合不合并」**。
        # 跨账户同人那类,正确答案正是「可能是同一位客户,但账户不同、不合并」—— 原来 YES 里有「同一客户」,
        # 这句会同时命中 YES 和 NO、判成「结论自相矛盾」。所以只看**合并动作**说没说,不看「是不是同一人」
        YES = tuple(x for x in YES if x not in ("同一位客户", "同一客户"))
        NO = tuple(x for x in NO if x not in ("不是同一", "非同一"))
        # 「合并 C21001 → C21000」这种只写方向的结论也算说了合并(10-17 示例库对比:
        # 结论、主档、迁移都写清了,只因为没出现「建议合并」四个字被判「没给结论」)。
        # 箭头那一段整体当成一个说法再过一遍否定检查,「不合并 A → B」仍然不算
        箭 = re.search(r"合并\s*\**\s*[A-Z]*\d+\s*\**\s*(?:→|->|⇒|并入)", text)
        d = tm.decide(text, YES + ((箭.group(0),) if 箭 else ()), NO)
        if d == want: return True, ""
        if d == "conflict":
            return False, "内容:同时说了合并和不合并 —— 结论不明确,不自动挑边"
        if d is None: return False, "内容:没给出明确的合并/不合并结论"
        return False, ("判成了同一人,应为不合并" if want == "no" else "判成了不同人,应为合并")

    # ③ 售后判责(BP-03):**责任归谁**必须说清,而且要给依据。
    #
    # 判责错了要赔钱,所以判分比别的严一档:
    # 光说「免费返修」不够 —— 得说清是**我方**的责任才免费,
    # 否则顾问会照着念给客户听,而客户听到的是「你们承认是你们的问题」。
    LIAB = {
        "工艺瑕疵 · 我方免费返修":         ("我方", ("免费返修", "免费修", "免费")),
        "尺寸偏差 · 记录完整 · 客方收费改": ("客方", ("收费", "客户承担", "客方")),
        "尺寸偏差 · 记录不全 · 我方免费改": ("我方", ("免费改", "免费")),
        # 2026-09-24 业务拍板加的两条(公差)。**超公差判我方、在公差内判客方** ——
        # 判分跟着判定表走,表加了行、这把尺子不跟,答对的会被判错(当天 V2 就挂了两条)。
        "尺寸偏差 · 超出公差 · 我方免费返修": ("我方", ("免费返修", "免费修", "免费")),
        "尺寸偏差 · 公差内 · 客方收费改":     ("客方", ("收费", "客户承担", "客方")),
        "尺寸偏差 · 签收已确认合身 · 客方收费改": ("客方", ("收费", "客户承担", "客方")),
        "尺寸偏差 · 试衣已签字 · 客方收费改":  ("客方", ("收费", "客户承担", "客方")),
        "尺寸偏差 · 该试没试 · 我方免费改":    ("我方", ("免费改", "免费")),
        "特性类已告知 · 无责解释":          ("无责", ("解释", "保养", "不返修", "无责")),
        "特性类未告知 · 我方让步":          ("我方", ("让步", "补偿", "协商")),
    }
    if truth_rc in LIAB:
        who, acts = LIAB[truth_rc]
        WHO = {"我方": ("我方", "我们的责任", "本店责任", "商家责任", "由我方"),
               "客方": ("客方", "客户责任", "客户承担", "使用不当"),
               "无责": ("无责", "不属于质量问题", "属正常特性", "不构成质量问题"),
               "分担": ("分担", "按合同", "双方")}[who]
        if not tm.mentions(text, WHO):
            return False, f"内容:没说清责任归谁(应为「{who}」)"
        if not tm.mentions(text, acts):
            return False, f"内容:没给出处理方式(应含 {acts[0]})"
        # 依据:判责必须能追到那张表,否则就是拍脑袋
        if not tm.mentions(text, ("第五节", "返修判定", "判定表", "告知", "量体记录",
                                  "工艺瑕疵", "特性", "公差", "试衣", "签收")):
            return False, "内容:没给判据 —— 判责必须说清依据哪一条,不能只给结论"
        return True, ""

    f = facts(case_id) if case_id else {}

    # ② 金额超额:必须同时报出请求金额与原支付金额这两个真实数字
    if truth_rc == "退款金额超过可退额":
        if not nums_in(text, f.get("req"), f.get("paid")):
            return False, f"内容:没同时报出请求 {f.get('req')} 与原支付 {f.get('paid')} 两个金额"
        return True, ""

    # ③ 超时但实际已退:必须引到那条 out+success 的流水号,且不得真的建议再退一次
    if truth_rc == "渠道超时但实际已退":
        # 库里的流水记录号和渠道流水号指的是**同一笔出账**,引哪个都算引到(2026-10-16 示例库对比真跑:
        # 回答引了渠道流水号 WX…、根因和「不得再退」都对,却因为没写 PFD2000O 被判挂 —— 判据只认一种写法)
        if f.get("out_id") and not any(x and x in text for x in (f["out_id"], f.get("out_serial"))):
            return False, f"内容:没引到已成功的出账流水 {f['out_id']}(渠道流水号 {f.get('out_serial')})"
        # 原来这里用的是自己那份 8 个词的正则、窗口只有 8 字 ——
        # 「**不得**重新发起退款」这类曾经被判成「真的建议了重发」。统一走 textmatch。
        #
        # ⚠️ **2026-10-26 又栽一次,而这次栽在「否定词离得远了点」上。**
        #    那次真跑(10-23 晚 V3)模型写的是
        #      「**禁止**在出账流水已显示 success 的情况下再次发起退款申请,否则会造成双倍出账」
        #    而判据把这一句读成「真的建议了『再次发起退款』」,整条判挂。
        #    **全文只有这一处命中** —— 模型那条真正的重试建议(「发起一次重试」)
        #    压根不在旧正则的覆盖里。也就是说:**判据抓的是模型自己写的那句禁止令。**
        #    「禁止」**早就在 `textmatch.NEG` 里**,缺的不是词,是窗口:默认回看 14 字,
        #    而这里否定词和动作之间插了一个 19 字的条件状语(「在…已显示 success 的情况下」)。
        #    textmatch 文件头自己写着「**中文的否定作用域到标点为止**,这条比调窗口大小可靠得多」,
        #    而代码里取的是「标点 or 14 字,谁短算谁」—— 标点那一头在这句里到不了,
        #    字数那一头先截断,于是那条原则在这一句上没生效。
        #    > **一个「模型真的建议了重发」和一个「模型明令禁止重发、只是否定词离得远」,
        #    > 在那条判挂的理由上长得一模一样** —— 而后者是答对了被判错。
        #    只在这条判据上把回看放宽到 60 字(支付这条路上的条件状语天生长),
        #    **不动全局默认**:放宽否定识别会让 must 类锚点更容易被判成「没说」。
        for m in re.finditer(重发的说法, text):
            if tm.negated(text, m.start(), span=60):
                continue
            # 在讲**后果**不是在建议(2026-10-16 示例库对比真跑:「如果再次发起……更严重的是幂等保护失效,
            # **导致**客户账户重复退款 800 元」被判成「建议了重复退款」)。看紧挨着的前文有没有后果 / 防范的词
            if re.search(r"(导致|造成|引发|以免|防止|避免|风险|可能|会|就会|否则)[^。\n;;]{0,8}$", text[max(0, m.start() - 12):m.start()]):
                continue
            # 用户 2026-10-26 拍的口径:提到重发**不是一律算错** —— 旁边必须同时贴着
            # 「先核实真实状态」和「用原幂等号、不换新号」两样,少一样才算错。
            if _重发带着防护(text, m.start()):
                continue
            return False, f"内容:真的建议了「{m.group(0)}」"
        return True, ""

    # ④ 其余三类没有可核对的数字,只认判别性词根
    ROOTS = {"原支付渠道已注销": r"注销", "商户账户余额不足": r"余额不足",
             "审批未完成即发起": r"审批", "幂等号重复提交": r"幂等"}
    pat = ROOTS.get(truth_rc)
    if pat and re.search(pat, text): return True, ""
    return False, f"内容:未指向真因「{truth_rc}」"

def truths():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return {r["case_id"]: dict(r) for r in c.execute("SELECT * FROM truth")}

def pick(n_bp01, n_bp02):
    """按真因分层取样,保证 6 类退款真因都被覆盖。"""
    T = truths()
    # ⚠️ 这里原来写的是 "待处理",而这两类**现在一条待处理的都没有** ——
    # 于是 t1/t2 全空、`pick()` 返回空列表,**评测取空了而不是报错**。
    # 取样要的是「这两类的全部工单」,它们处理到哪一步和分层取样没关系。
    t1 = [t for t in api.list_tasks("财务人工任务", api.看全部任务)]
    t2 = [t for t in api.list_tasks("客户合并确认", api.看全部任务)]
    seen, out = {}, []
    for t in t1:                                   # 先每类真因取一个
        rc = T.get(t["ref_id"], {}).get("root_cause")
        if rc and rc not in seen: seen[rc] = 1; out.append(t)
    # ⚠️ **补足也只补有真值的**(2026-10-15)。
    # 上面那个循环按真因去重时查了 `T.get(...)`,而这个补足循环原来**不查** ——
    # 现在库里所有财务工单恰好都有真值,所以它从没暴露过。
    # 而 2026-10-15 要往队列里造「能跑的未研判工单」给用户点,
    # 那些单**不写 `truth`**(truth 是评测答案,编一份真值等于把分子分母一起编掉) ——
    # 它们一进库,这个循环就会把没有真值的单补进评测,判分器拿不到真值。
    # > 一个「这道题模型答错了」和一个「这道题根本没有标准答案」,
    # > **在成绩单上长得一模一样。**
    # 加上这个条件之后结果不变(现有的单都有真值),变的是**以后不会错**。
    for t in t1:                                   # 再补足
        if len(out) >= n_bp01: break
        if t not in out and T.get(t["ref_id"], {}).get("root_cause"):
            out.append(t)
    seen2, out2 = {}, []
    for t in t2:
        rc = T.get(t["id"][1:], {}).get("root_cause")
        if rc and seen2.get(rc, 0) < n_bp02 // 2: seen2[rc] = seen2.get(rc, 0) + 1; out2.append(t)
    return out[:n_bp01] + out2[:n_bp02]

def main():
    n1 = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    n2 = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    T, pv = truths(), v1.provider()
    tasks = pick(n1, n2)
    print(f"供应商 {pv['id']} / 模型 {pv['model']} / {len(tasks)} 道题\n" + "=" * 92, flush=True)
    def 跑一轮():
        recs = []
        for i, t in enumerate(tasks, 1):
            if t["type"] == "财务人工任务":
                prompt, case, bp = v1.BP01.format(ref=t["ref_id"]), t["ref_id"], "BP-01"
            else:
                a, b = t["ref_id"].split("|")
                prompt, case, bp = v1.BP02.format(a=a, b=b), t["id"][1:], "BP-02"
            tr = T.get(case, {})
            try:
                r = v1.run_case(pv, prompt, purpose=("退款定因" if bp=="BP-01" else "客户合并"))
            except Exception as e:
                r = dict(finding=None, error=str(e)[:160])
            f = r.get("finding")
            text = json.dumps(f, ensure_ascii=False) if f else ""
            ok, why = (hit(text, tr.get("root_cause", ""), case) if f
                       else (False, f"跑挂了:{r.get('error', '未提交')}" if r.get("error")
                             else "未提交"))
            r.update(case=case, bp=bp, truth=tr.get("root_cause"), passed=ok, why=why,
                     expected_action=tr.get("expected_action"))
            recs.append(r)
            print(f"[{i:2d}] {'✅' if ok else '❌'} {case:10s} {bp}  "
                  f"真因 {str(tr.get('root_cause'))[:12]:12s} "
                  f"{r.get('calls','-'):>2}调 {r.get('seconds','-'):>5}s "
                  f"${r.get('cost_local',0):.4f}  {why[:34]}", flush=True)
            time.sleep(1.5)                             # 让一让额度
        return recs

    # **跑两轮、判基线来路、部分不写** —— 见 rounds.跑并收尾。
    # ⚠️ 这一份原来**连来路章都没盖**:直接 json.dump,文件里没有供应商/模型/代码,
    # 于是它的基线永远不可比(rounds 会拒收)。走共用件后默认用 evalrec.dump,章就盖上了。
    # 全集 = 默认题量(12 + 8)挑出来的那批;命令行传小了就是部分跑,不许覆盖。
    import rounds
    全集 = len(pick(12, 8))
    recs, _ = rounds.跑并收尾(跑一轮, 名="V1 退款定因/客户合并", 键="case",
                              结果文件=os.path.join(HERE, "eval-results.jsonl"),
                              全集数=全集, 本轮数=len(tasks))
    p = sum(r["passed"] for r in recs)
    print("=" * 92)
    print(f"最后一轮 命中 {p}/{len(recs)} = {p/max(len(recs),1)*100:.0f}%  |  "
          f"成本 ${sum(r.get('cost_local',0) for r in recs):.4f}  |  "
          f"调用 {sum(r.get('calls',0) for r in recs)} 次  |  "
          f"耗时 {sum(r.get('seconds',0) for r in recs):.0f}s(最后一轮)")

def rescore():
    """只重判,不重跑模型 —— 模型结果已存盘,改评分规则不用再花钱。"""
    p = os.path.join(HERE, "eval-results.jsonl")
    recs = [json.loads(l) for l in open(p, encoding="utf-8")]
    changed = 0
    for r in recs:
        f = r.get("finding")
        text = json.dumps(f, ensure_ascii=False) if f else ""
        ok, why = hit(text, r.get("truth") or "", r.get("case")) if f else (False, r.get("error", "未提交"))
        if ok != r.get("passed"): changed += 1
        r["passed"], r["why"] = ok, why
        r.pop("judge", None)      # 老结果文件里那个字段名,重判时顺手去掉,别留两份
    with open(p, "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    pn = sum(r["passed"] for r in recs)
    print(f"重判 {len(recs)} 条,判定翻转 {changed} 条")
    print(f"命中 {pn}/{len(recs)} = {pn/len(recs)*100:.0f}%")
    for r in recs:
        print(f"  {'✅' if r['passed'] else '❌'} {r['case']:10s} {r['bp']}  "
              f"真因 {str(r.get('truth'))[:12]:12s} {str(r['why'])[:44]}")
    return recs

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rescore": rescore()
    else: main()
