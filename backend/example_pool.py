# -*- coding: utf-8 -*-
"""研判示例库 · 一期(用户 2026-10-16 拍:方案 B 按关键特征挑;只有一条的根因一期全留评测)。

方案全文:`intent/澜绣云裳agent-研判示例库方案.md`。这里只做四件事:

  切分 —— 建库标注按根因分层:每种根因取编号最靠后的 ⌊n/3⌋ 条进示例池,其余留评测。
           只有一两条的根因 ⌊n/3⌋=0,**自然全留评测**(评测的根因覆盖面一类不少)。
           取「最靠后」:几个老测试写死了最前面的退款单(D2000 / D2008 / D2012 / D2016),
           按 id 取头几条的评测(gen_compare / liability_eval)也取前面的。
           切分结果**冻结**在 `agent/example-pool.json`,以后不重切;重切 = 新分界点。
  特征 —— 每类工单的「关键特征」,都从库里现算,不手写:
           退款看渠道返回码序列 + 支付流水里有没有出账成功;合并看两条档案哪几项相同 / 不同;
           售后看报修问题 + 尺寸差了哪几项。
  挑   —— 同一断点的示例池里,特征重合最多的优先,最多 3 条;**永不挑当前这一单自己**。
  成段 —— 拼成提示词里的「参考示例」一段:特征 + 人认定的根因 / 处理 / 证据。
           **不放 AI 自己的草稿**(会把 AI 的说法自我强化);不放姓名 / 手机号(特征里只有「相同 / 不同」)。

⚠️ **一个已知的、而且很要紧的局限**(用户 2026-10-16 知情选择「基础设施照做,涨分不算数」):
现有标注里,退款的六种根因各对应一种渠道返回码,**特征和答案一一对应** —— 按返回码挑出来的示例,
照抄它的根因就一定对。所以开示例之后的涨分是「查表」,不是「会判了」。
要真正测出示例有没有用,得有「表面一样、根因不同」的真实案例(比如返回超时、但钱确实没退),
那要业务逐例给真值,造数不能自己编。

⚠️ 示例池是**评测答案的一部分**,只给研判提示词用,不进智能体的任何工具。
"""
import json, os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "lanxiu.db")
冻结文件 = os.path.join(ROOT, "agent", "example-pool.json")
断点们 = ("BP-01", "BP-02", "BP-03")
每次最多 = 3


def _c(db=None):
    c = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def 切(db=None):
    """按根因分层切。返回 {"示例池": [...], "评测": [...]},每项 {case_id, bp, 根因}。"""
    c = _c(db)
    try:
        行 = c.execute("SELECT case_id, breakpoint, root_cause FROM truth WHERE src='建库标注' "
                      "AND breakpoint IN (%s) ORDER BY breakpoint, root_cause, case_id"
                      % ",".join("?" * len(断点们)), 断点们).fetchall()
    finally:
        c.close()
    组 = {}
    for r in 行:
        组.setdefault((r["breakpoint"], r["root_cause"]), []).append(r["case_id"])
    池, 评 = [], []
    for (bp, 根因), ids in sorted(组.items()):
        k = len(ids) // 3
        for i, cid in enumerate(ids):
            (池 if i >= len(ids) - k else 评).append(dict(case_id=cid, bp=bp, 根因=根因))
    return dict(示例池=池, 评测=评)


def 冻(db=None):
    import subprocess
    分 = 切(db)
    try:
        头 = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        头 = "(取不到)"
    doc = {"说明": "研判示例库的切分(一期)。示例池只给产品研判提示词当参考;评测只许用「评测」这一份。"
                   "按根因分层,每种根因取编号最靠后的 ⌊n/3⌋ 条进示例池 —— 只有一两条的根因全留评测。"
                   "重切 = 新分界点,不许悄悄改这份文件。",
           "切于提交": 头, **分}
    with open(冻结文件, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


def 冻结的():
    with open(冻结文件, encoding="utf-8") as f:
        return json.load(f)


def 示例池ids():
    return {x["case_id"] for x in 冻结的()["示例池"]}


def 评测ids(bp=None):
    """以后任何**走产品研判提示词**的评测,题只许从这里取。"""
    return {x["case_id"] for x in 冻结的()["评测"] if bp is None or x["bp"] == bp}


# ── 关键特征(都从库里现算)────────────────────────────────────────────
def 特征(bp, case_id, db=None):
    """返回 {特征名: 值} —— 值都是代码 / 相同不同 / 报修类型,不带姓名手机号。"""
    c = _c(db)
    try:
        if bp == "BP-01":
            码 = [r[0] for r in c.execute(
                "SELECT resp_code FROM refund_trace WHERE deposit_id=? ORDER BY attempt", (case_id,))]
            出 = c.execute("SELECT 1 FROM payment_flow WHERE deposit_id=? AND direction='out' AND status='success' LIMIT 1",
                          (case_id,)).fetchone()
            return {"渠道返回码": ">".join(dict.fromkeys(码)) or "(无)", "支付流水有出账成功": "是" if 出 else "否"}
        if bp == "BP-02":
            t = c.execute("SELECT ref_id FROM task WHERE id=?", ("T" + case_id,)).fetchone()
            if not t or "|" not in (t[0] or ""):
                return {}
            a, b = t[0].split("|")
            A = c.execute("SELECT * FROM customer WHERE id=?", (a,)).fetchone()
            B = c.execute("SELECT * FROM customer WHERE id=?", (b,)).fetchone()
            if not (A and B):
                return {}
            return {k: ("相同" if (A[k] or "") == (B[k] or "") else "不同")
                    for k in ("name", "phone", "birthday", "addr", "city", "shop") if k in A.keys()}
        if bp == "BP-03":
            m = c.execute("SELECT * FROM maintain WHERE id=?", (case_id,)).fetchone()
            if not m:
                return {}
            差 = {}
            if "尺寸差" in m.keys() and m["尺寸差"]:
                try:
                    差 = json.loads(m["尺寸差"]) or {}
                except Exception:
                    差 = {}
            return {"报修问题": m["issue"] or "(无)", "尺寸差了哪几项": "、".join(sorted(差)) or "(无)"}
    finally:
        c.close()
    return {}


# ── 挑 ────────────────────────────────────────────────────────────
def 挑(bp, case_id, db=None, k=每次最多):
    """同一断点的示例池里,特征重合最多的 k 条;**永不挑这一单自己**。返回 [{case_id, 重合, 特征}]。"""
    我 = 特征(bp, case_id, db)
    候 = []
    for x in 冻结的()["示例池"]:
        if x["bp"] != bp or x["case_id"] == case_id:
            continue
        f = 特征(bp, x["case_id"], db)
        重合 = sum(1 for kk, v in 我.items() if f.get(kk) == v)
        候.append(dict(case_id=x["case_id"], 重合=重合, 特征=f))
    候.sort(key=lambda y: (-y["重合"], y["case_id"]))
    return 候[:k]


def 示例段(bp, case_id, db=None):
    """拼成提示词里的「参考示例」一段;挑不出就返回 ("", [])。"""
    选 = 挑(bp, case_id, db)
    if not 选:
        return "", []
    c = _c(db)
    try:
        标 = {r["case_id"]: r for r in c.execute(
            "SELECT case_id, root_cause, expected_action, expected_evidence FROM truth WHERE case_id IN (%s)"
            % ",".join("?" * len(选)), [x["case_id"] for x in 选])}
    finally:
        c.close()
    段 = ["\n参考示例(过去人核过的同类工单,**只作参考**:先按上面的要求查这一单自己的材料,"
          "特征看着像也可能根因不同,不许照抄示例的结论):"]
    for i, x in enumerate(选, 1):
        r = 标.get(x["case_id"])
        if not r:
            continue
        特 = ";".join(f"{k}={v}" for k, v in x["特征"].items())
        段.append(f"示例{i}:特征 {特}\n  人认定的根因:{r['root_cause']}\n  处理:{r['expected_action']}\n"
                 f"  依据:{r['expected_evidence'] or '(未记)'}")
    return "\n".join(段) + "\n", [x["case_id"] for x in 选]
