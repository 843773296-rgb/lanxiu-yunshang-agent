#!/usr/bin/env python3
"""智能运维平台的数据层 —— 队列、研判台账、销账、回流、健康度。

和「展示件」的分界线全在这个文件里:

  展示件            平台
  ────────────────  ──────────────────────────────────────────
  你点它才跑         积压在那儿等着被跑完
  跑完显示一次       落库,谁都能回头看当时说了什么、花了多少钱
  有标准答案可判分   **上线后没有标准答案**,只有人采不采纳
  跑完就结束         人的裁决回流成新标注,下次回归用得上

最后一条是这套东西能不能越用越准的关键。评测集不是上线前写完就冻住的,
是值班同学每否掉一条就长一条。
"""
import json, os, sqlite3, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

# 时效承诺。定在这里而不是散在页面上,是因为它是**业务承诺**,不是显示逻辑。
# 退款失败压着客户的钱,比客户合并急。
SLA_HOURS = {"财务人工任务": 24, "客户合并确认": 48}
DEFAULT_SLA = 48

DECISIONS = ("已采纳", "已改判", "已升级")


def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def _rows(sql, *a):
    with _c() as c: return [dict(r) for r in c.execute(sql, a)]


def now():
    return dt.datetime.now().replace(microsecond=0)


def _dt(s):
    if not s: return None
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return dt.datetime.strptime(s, f)
        except ValueError: continue
    return None


# ── 一、队列 ────────────────────────────────────────────────────────────
def queue(state=None):
    """值班队列。每条带:等了多久、离超时还有多久、智能体研判到哪一步了。

    「等了多久」是运维平台和展示件体感差别最大的一个字段 ——
    展示件里没有时间,平台里时间是压力。
    """
    latest = {}
    for t in _rows("SELECT * FROM triage ORDER BY id"):
        latest[t["task_id"]] = t          # 同一工单研判多次,取最后一次

    out, n = [], now()
    for t in _rows("SELECT * FROM task ORDER BY created"):
        created = _dt(t["created"]) or n
        waited_h = (n - created).total_seconds() / 3600
        sla = SLA_HOURS.get(t["type"], DEFAULT_SLA)
        tr = latest.get(t["id"])
        st = "未研判" if not tr else tr["status"]
        done = st in DECISIONS
        if done:                       # 已销账的不再计时效
            level, left = "已销账", None
        else:
            left = sla - waited_h
            level = "已超时" if left <= 0 else ("临期" if left <= sla * 0.25 else "正常")
        out.append(dict(
            task_id=t["id"], type=t["type"], ref=t["ref_id"], created=t["created"],
            waited_h=round(waited_h, 1), sla_h=sla, left_h=None if left is None else round(left, 1),
            level=level, state=st, done=done,
            triage_id=tr["id"] if tr else None,
            ai_root_cause=tr["ai_root_cause"] if tr else None,
            ai_confidence=tr["ai_confidence"] if tr else None,
            cost=tr["cost"] if tr else None,
        ))
    if state == "待办":  out = [x for x in out if not x["done"]]
    elif state == "未研判": out = [x for x in out if x["state"] == "未研判"]
    elif state == "待复核": out = [x for x in out if x["state"] == "待复核"]
    elif state == "已销账": out = [x for x in out if x["done"]]
    # 超时的排最前,然后按等待时长倒序 —— 队列的排序本身就是一种业务规则
    rank = {"已超时": 0, "临期": 1, "正常": 2, "已销账": 3}
    out.sort(key=lambda x: (rank[x["level"]], -x["waited_h"]))
    return out


def backlog():
    """积压看板。看的是「今天还剩多少件」,不是「历史一共多少件」。"""
    q = queue()
    todo = [x for x in q if not x["done"]]
    by_state, by_type = {}, {}
    for x in todo:
        by_state[x["state"]] = by_state.get(x["state"], 0) + 1
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
    over = [x for x in todo if x["level"] == "已超时"]
    return dict(
        总量=len(q), 待办=len(todo), 已销账=len(q) - len(todo),
        已超时=len(over), 临期=len([x for x in todo if x["level"] == "临期"]),
        最久未处理小时=round(max([x["waited_h"] for x in todo], default=0), 1),
        按状态=by_state, 按类型=by_type,
        待复核=len([x for x in todo if x["state"] == "待复核"]),
        未研判=len([x for x in todo if x["state"] == "未研判"]),
    )


# ── 二、研判结果落库 ─────────────────────────────────────────────────────
SECTIONS = [("ai_root_cause", ("根因", "根本原因", "真因")),
            ("ai_action",     ("建议动作", "建议处理", "处理动作", "建议")),
            ("ai_evidence",   ("证据", "支撑证据", "依据")),
            ("_conf",         ("置信度", "信心"))]

# 段名后面允许跟的分隔符。**不允许跟正文** —— 这一条是踩出来的:
# 模型在「置信度」那段里写了一句「根因(金额超限)置信度高;……」,
# 旧规则把它当成新的「根因」标题,**把前面真正的根因段覆盖成了空**。
# 内容明明是对的,产品侧拿到的却是空字段 —— 这种失败不看解析结果根本发现不了。
_SEP = "：:／/|｜、-—– 	"
_WRAP = ("", "**", "##", "###", "-", "*", "#")


def _heading(line):
    """这一行是不是段标题?返回 (字段名, 同行正文) 或 None。"""
    for w in _WRAP:
        l = line[len(w):].lstrip() if w and line.startswith(w) else (line if not w else None)
        if l is None: continue
        l = l.rstrip("* ")
        for key, names in SECTIONS:
            for nm in names:
                if l == nm: return key, ""
                if l.startswith(nm) and l[len(nm)] in _SEP:
                    return key, l[len(nm):].lstrip(_SEP).strip(" *#")
    return None


def parse_draft(text):
    """把智能体的四段草稿切成字段。

    没有用「让模型调一个写工具交结构化结果」的做法 —— 那会给智能体开第一个写权限,
    而**工具全部只读**是这套系统最硬的一条保证,不值得为了省一段解析代码破掉。
    代价是解析会失败;解析失败不藏着,直接变成一个运维指标(见 health() 的协议失败率)。

    **先出现的段落算数**:同一个段名第二次出现时不覆盖已有内容。
    模型经常在结尾回顾时把段名再写一遍,那是复述,不是新段落。
    """
    got, cur = {}, None
    for raw in (text or "").split("\n"):
        l = raw.strip()
        h = _heading(l)
        if h:
            cur, body = h
            if got.get(cur): cur = None           # 这一段已经有内容了,后面的重复段名不算
            elif body: got[cur] = body
            else: got.setdefault(cur, "")
        elif cur and l:
            got[cur] = (got.get(cur, "") + " " + l).strip()
    return {k: got.get(k, "") for k, _ in SECTIONS}


def confidence(trajectory, parsed, need_tools=2):
    """置信度由**过程信号**推,不看模型自称,也不看答得对不对。

    上线后没有标准答案 —— 「对不对」这个信号在生产里根本拿不到。
    能拿到的只有:查了几次数据、有没有给出可核对的证据、四段是否齐全。
    模型自称的置信度不用,因为它高兴的时候什么都敢说「高」。
    """
    n = len([t for t in (trajectory or []) if t.get("tool")])
    full = all(parsed.get(k) for k in ("ai_root_cause", "ai_action", "ai_evidence"))
    if not parsed.get("ai_root_cause"):
        return "低"                                   # 连根因都没给,人必须看
    if n >= need_tools and full:
        return "高"
    if n >= 1 and parsed.get("ai_root_cause"):
        return "中"
    return "低"


def save_triage(task_id, breakpoint, case_id, text, trajectory,
                cost=None, latency_ms=None, model=None, usage=None,
                guard_blocked=False, guard_violations=None, answer_turns=1):
    p = parse_draft(text)
    conf = confidence(trajectory, p)
    with _c() as c:
        cur = c.execute(
            "INSERT INTO triage(task_id,breakpoint,case_id,created,ai_root_cause,ai_action,"
            "ai_evidence,ai_confidence,ai_text,tool_calls,cost,latency_ms,model,"
            "in_tokens,out_tokens,cache_read,guard_blocked,guard_violations,answer_turns,status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'待复核')",
            (task_id, breakpoint, case_id, now().strftime("%Y-%m-%d %H:%M:%S"),
             p["ai_root_cause"], p["ai_action"], p["ai_evidence"], conf, text,
             len(trajectory or []), cost, latency_ms, model,
             (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens"),
             (usage or {}).get("cache_read_input_tokens"),
             1 if guard_blocked else 0,
             json.dumps(guard_violations or [], ensure_ascii=False), answer_turns))
        c.execute("UPDATE task SET status='待复核', summary=? WHERE id=?",
                  (p["ai_root_cause"][:60] or "(未解析出根因)", task_id))
        return cur.lastrowid


def reparse(only_failed=True):
    """解析器改好之后,把历史研判重新解析一遍 —— **不用重新调模型**。

    这就是把 ai_text 全文存下来的理由。展示件不存,因为跑完就不看了;
    平台必须存:解析规则、置信度规则以后一定会改,改完要能对历史重算,
    否则「协议失败率」这个指标在改规则那天会断档,前后不可比。
    只改解析出来的字段,**不动人工裁决**。
    """
    fixed = []
    with _c() as c:
        rows = c.execute("SELECT id,ai_text,ai_root_cause,tool_calls FROM triage").fetchall()
        for r in rows:
            if only_failed and r["ai_root_cause"]: continue
            p = parse_draft(r["ai_text"] or "")
            if p["ai_root_cause"] == (r["ai_root_cause"] or ""): continue
            conf = confidence([{"tool": 1}] * (r["tool_calls"] or 0), p)
            c.execute("UPDATE triage SET ai_root_cause=?,ai_action=?,ai_evidence=?,"
                      "ai_confidence=? WHERE id=?",
                      (p["ai_root_cause"], p["ai_action"], p["ai_evidence"], conf, r["id"]))
            fixed.append(dict(id=r["id"], root_cause=p["ai_root_cause"][:50], confidence=conf))
    for f in fixed:
        with _c() as c:
            c.execute("UPDATE task SET summary=? WHERE id=(SELECT task_id FROM triage WHERE id=?)",
                      (f["root_cause"][:60], f["id"]))
    return fixed


def get_triage(triage_id):
    r = _rows("SELECT * FROM triage WHERE id=?", triage_id)
    return r[0] if r else None


# ── 三、销账与回流 ───────────────────────────────────────────────────────
def resolve(triage_id, decision, handler, root_cause=None, action=None, note=None):
    """值班同学销账。**改判会回流成新的标注** —— 这是平台能越用越准的唯一通路。

    回流写的是 truth 表,标 src='人工改判'。为什么要分开标:
    回流条目只经过一个人的判断、没有第二个人复核过,
    如果和建库标注混在一起,一次判错的裁决会悄悄变成"标准答案",而且再也查不出来。
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision 只能是 {DECISIONS},收到 {decision}")
    t = get_triage(triage_id)
    if not t: raise ValueError(f"没有 triage#{triage_id}")
    ts = now().strftime("%Y-%m-%d %H:%M:%S")
    flowed, conflict = False, None
    with _c() as c:
        c.execute("UPDATE triage SET status=?,human_root_cause=?,human_action=?,"
                  "human_note=?,handler=?,handled_at=? WHERE id=?",
                  (decision, root_cause, action, note, handler, ts, triage_id))
        c.execute("UPDATE task SET status=? WHERE id=?",
                  ("已升级" if decision == "已升级" else "已处理", t["task_id"]))
        if decision == "已改判" and t["case_id"] and root_cause:
            old = c.execute("SELECT root_cause,src FROM truth WHERE case_id=?",
                            (t["case_id"],)).fetchone()
            if old and old["src"] == "建库标注" and old["root_cause"] != root_cause:
                # **不覆盖**。上线前的标注是复核过的,值班同学的裁决只经一个人。
                # 谁对谁错这里定不了 —— 定不了的事就别偷偷替对方做决定,记下来给人裁。
                # 和相容矩阵里「人工确认 vs 规则不一致就列出来」是同一条处理原则。
                conflict = dict(case_id=t["case_id"], 建库标注=old["root_cause"], 人工改判=root_cause)
            elif old and old["root_cause"] == root_cause:
                flowed = True          # 和已有标注一致,不用重复写
            else:
                c.execute("INSERT OR REPLACE INTO truth(case_id,breakpoint,root_cause,"
                          "expected_action,expected_evidence,note,src) VALUES(?,?,?,?,?,?,'人工改判')",
                          (t["case_id"], t["breakpoint"], root_cause, action or "",
                           note or "", f"{handler} 于 {ts} 改判回流"))
                flowed = True
            if flowed: c.execute("UPDATE triage SET into_eval=1 WHERE id=?", (triage_id,))
    return dict(triage_id=triage_id, decision=decision, 回流评测集=flowed, 与建库标注冲突=conflict)


# ── 四、健康度 ──────────────────────────────────────────────────────────
def health():
    """智能体自己的运维指标。

    生产里衡量质量的不是「判对了几道」(没有标准答案),是 **人采纳了几条**。
    采纳率掉下来,不用等谁投诉,队列自己就会告诉你。
    """
    tr = _rows("SELECT * FROM triage")
    done = [t for t in tr if t["status"] in DECISIONS]
    adopted = [t for t in done if t["status"] == "已采纳"]
    costs = [t["cost"] for t in tr if t["cost"] is not None]
    lats = [t["latency_ms"] for t in tr if t["latency_ms"]]
    unparsed = [t for t in tr if not t["ai_root_cause"]]
    conf = {}
    for t in tr: conf[t["ai_confidence"]] = conf.get(t["ai_confidence"], 0) + 1
    # 高置信度里被人改判的 —— 最该盯的一个数:它说明置信度本身在骗人
    hi_wrong = [t for t in done if t["ai_confidence"] == "高" and t["status"] == "已改判"]
    ev = _rows("SELECT src,COUNT(*) n FROM truth GROUP BY src")
    # 值班裁决和上线前标注对不上的 case —— 这个数不该是 0,也不该一直涨。
    # 一直是 0 说明没人真在复核;一直涨说明标注或者业务规则该修了。
    clash = _rows("SELECT COUNT(*) n FROM triage t JOIN truth u ON u.case_id=t.case_id"
                  " WHERE t.status='已改判' AND u.src='建库标注'"
                  " AND t.human_root_cause IS NOT NULL AND t.human_root_cause<>u.root_cause")[0]["n"]
    return dict(
        研判总数=len(tr), 已销账=len(done),
        采纳率=f"{len(adopted)/len(done)*100:.0f}%" if done else "—",
        改判率=f"{len([t for t in done if t['status']=='已改判'])/len(done)*100:.0f}%" if done else "—",
        升级率=f"{len([t for t in done if t['status']=='已升级'])/len(done)*100:.0f}%" if done else "—",
        协议失败率=f"{len(unparsed)/len(tr)*100:.0f}%" if tr else "—",
        协议失败数=len(unparsed),
        高置信度被改判=len(hi_wrong),
        累计成本=round(sum(costs), 4) if costs else 0.0,
        单条均价=round(sum(costs)/len(costs), 4) if costs else None,
        中位耗时秒=round(sorted(lats)[len(lats)//2]/1000, 1) if lats else None,
        置信度分布=conf,
        体检打回率=(f"{sum(1 for t in tr if t['guard_blocked'])/len(tr)*100:.0f}%" if tr else "—"),
        体检打回数=sum(1 for t in tr if t["guard_blocked"]),
        缓存命中率=(f"{sum(t['cache_read'] or 0 for t in tr)/max(sum(t['in_tokens'] or 0 for t in tr),1)*100:.0f}%"
                if any(t["in_tokens"] for t in tr) else "—"),
        评测集来源={r["src"]: r["n"] for r in ev}, 与建库标注冲突=clash,
    )


if __name__ == "__main__":
    print("智能运维平台 · 数据层自测\n" + "=" * 70)
    b = backlog()
    print(f"积压 {b['待办']}/{b['总量']}  超时 {b['已超时']}  临期 {b['临期']}  "
          f"最久 {b['最久未处理小时']}h")
    print("  按类型:", b["按类型"])
    q = queue("待办")
    print(f"\n队列前 5(超时优先):")
    for x in q[:5]:
        print(f"  [{x['level']:4s}] {x['task_id']:8s} {x['type']:8s} "
              f"等了 {x['waited_h']:7.1f}h / SLA {x['sla_h']}h  状态 {x['state']}")
    print("\n四段解析自测:")
    demo = ("根因：渠道超时但实际已退款\n"
            "建议动作：不得重新发起退款，先向渠道核对流水 CH20260814001\n"
            "证据：refund_trace 显示第 3 次重试返回 TIMEOUT，payment_flow 有 direction=out 成功记录\n"
            "置信度：高")
    p = parse_draft(demo)
    for k, v in p.items(): print(f"  {k:15s} {v[:52]}")
    assert p["ai_root_cause"].startswith("渠道超时"), "根因没解析出来"
    assert "不得重新发起" in p["ai_action"], "动作没解析出来"
    assert confidence([{"tool": "a"}, {"tool": "b"}], p) == "高"
    assert confidence([], p) == "低", "一次数据都没查就下结论,不该给高/中"
    assert confidence([{"tool": "a"}], parse_draft("我觉得应该是超时")) == "低", "没有根因该判低"

    # 两条**线上真实踩过的**格式,加进自测防回归:
    # ① 段名独占一行、正文在下一行,而且结尾又提了一次段名(旧规则会把前面覆盖成空)
    a = parse_draft("根因\n金额写错为 2250 元,超过原收款\n\n建议动作\n按 1500 元重发\n\n"
                    "证据\nreq_amount 均为 2250\n\n置信度\n根因(金额超限)置信度高;来源待核")
    assert a["ai_root_cause"].startswith("金额写错"), f"结尾复述段名把正文覆盖了:{a['ai_root_cause']!r}"
    assert a["ai_action"].startswith("按 1500"), a["ai_action"]
    # ② 段名和正文同一行,用「 / 」分隔
    b = parse_draft("根因 / 三次重试用了三个不同幂等号\n\n建议动作 / 先查渠道单\n\n证据 / 无 out 流水")
    assert b["ai_root_cause"].startswith("三次重试"), b["ai_root_cause"]
    assert b["ai_evidence"].startswith("无 out"), b["ai_evidence"]
    print("  ✅ 两条线上真实格式(段名独占行+结尾复述 / 段名与正文同行)都能解析")
    print("\n健康度:", json.dumps(health(), ensure_ascii=False))
    print("\n✅ 数据层自测通过")
