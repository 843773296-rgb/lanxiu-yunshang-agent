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
                resp=tr["resp_code"] if tr else None)

def nums_in(text, *vals):
    """答案里是否出现了这些真实金额(允许 800 / 800.0 / 800.00 / 1,200 几种写法)。"""
    import re
    for v in vals:
        if v is None: return False
        pats = {f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:,.0f}"}
        if not any(re.search(re.escape(pt) + r"(?!\d)", text) for pt in pats): return False
    return True

DECIDE_NO = r"(不合并|不建议合并|不应合并|不予合并|不能合并|不是同一|非同一|保持独立|各自独立|分别保留)"
DECIDE_YES = r"(建议合并|应当合并|应该合并|可以合并|予以合并|确认合并|同一位?客户)"

def hit(text, truth_rc, case_id=None):
    """返回 (是否命中, 说明)。判据尽量落在库里的真实数字上。"""
    import re

    # ① 客户合并:直接抽"合并 / 不合并"这个决定,否定式优先匹配
    if truth_rc == "同名不同人":
        if re.search(DECIDE_NO, text):  return True, ""
        if re.search(DECIDE_YES, text): return False, "判成了同一人,应为不合并"
        return False, "没给出明确的合并/不合并结论"
    if truth_rc == "同一客户跨店重复建档":
        if re.search(DECIDE_NO, text):  return False, "判成了不同人,应为合并"
        if re.search(DECIDE_YES, text): return True, ""
        return False, "没给出明确的合并/不合并结论"

    f = facts(case_id) if case_id else {}

    # ② 金额超额:必须同时报出请求金额与原支付金额这两个真实数字
    if truth_rc == "退款金额超过可退额":
        if not nums_in(text, f.get("req"), f.get("paid")):
            return False, f"没同时报出请求 {f.get('req')} 与原支付 {f.get('paid')} 两个金额"
        return True, ""

    # ③ 超时但实际已退:必须引到那条 out+success 的流水号,且不得真的建议再退一次
    if truth_rc == "渠道超时但实际已退":
        if f.get("out_id") and f["out_id"] not in text:
            return False, f"没引到已成功的出账流水 {f['out_id']}"
        for m in re.finditer(r"(再次|重新|重复)(发起|提交)?退款", text):
            before = text[max(0, m.start() - 8):m.start()]
            if not re.search(r"(不|勿|无需|避免|禁止|严禁|切勿|而非)", before):
                return False, f"真的建议了「{m.group(0)}」"
        return True, ""

    # ④ 其余三类没有可核对的数字,只认判别性词根
    ROOTS = {"原支付渠道已注销": r"注销", "商户账户余额不足": r"余额不足",
             "审批未完成即发起": r"审批", "幂等号重复提交": r"幂等"}
    pat = ROOTS.get(truth_rc)
    if pat and re.search(pat, text): return True, ""
    return False, f"未指向真因「{truth_rc}」"

def truths():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return {r["case_id"]: dict(r) for r in c.execute("SELECT * FROM truth")}

def pick(n_bp01, n_bp02):
    """按真因分层取样,保证 6 类退款真因都被覆盖。"""
    T = truths()
    t1 = [t for t in api.list_tasks("财务人工任务", "待处理")]
    t2 = [t for t in api.list_tasks("客户合并确认", "待处理")]
    seen, out = {}, []
    for t in t1:                                   # 先每类真因取一个
        rc = T.get(t["ref_id"], {}).get("root_cause")
        if rc and rc not in seen: seen[rc] = 1; out.append(t)
    for t in t1:                                   # 再补足
        if len(out) >= n_bp01: break
        if t not in out: out.append(t)
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
        ok, why = hit(text, tr.get("root_cause", ""), case) if f else (False, r.get("error", "未提交"))
        r.update(case=case, bp=bp, truth=tr.get("root_cause"), passed=ok, judge=why,
                 expected_action=tr.get("expected_action"))
        recs.append(r)
        print(f"[{i:2d}] {'✅' if ok else '❌'} {case:10s} {bp}  "
              f"真因 {str(tr.get('root_cause'))[:12]:12s} "
              f"{r.get('calls','-'):>2}调 {r.get('seconds','-'):>5}s "
              f"${r.get('cost_local',0):.4f}  {why[:34]}", flush=True)
        time.sleep(1.5)                             # 让一让额度
    with open(os.path.join(HERE, "eval-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    p = sum(r["passed"] for r in recs)
    print("=" * 92)
    print(f"命中 {p}/{len(recs)} = {p/len(recs)*100:.0f}%  |  "
          f"总成本 ${sum(r.get('cost_local',0) for r in recs):.4f}  |  "
          f"总调用 {sum(r.get('calls',0) for r in recs)} 次  |  "
          f"总耗时 {sum(r.get('seconds',0) for r in recs):.0f}s")

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
        r["passed"], r["judge"] = ok, why
    with open(p, "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    pn = sum(r["passed"] for r in recs)
    print(f"重判 {len(recs)} 条,判定翻转 {changed} 条")
    print(f"命中 {pn}/{len(recs)} = {pn/len(recs)*100:.0f}%")
    for r in recs:
        print(f"  {'✅' if r['passed'] else '❌'} {r['case']:10s} {r['bp']}  "
              f"真因 {str(r.get('truth'))[:12]:12s} {r['judge'][:44]}")
    return recs

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rescore": rescore()
    else: main()
