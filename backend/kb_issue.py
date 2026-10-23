# -*- coding: utf-8 -*-
"""知识问题处理入口 —— 门店这一侧(外部复审第 4 节 E · 最小一刀,用户 2026-10-23 拍「A–E 全做」)。

## 要解决的事

员工在 chat 里问知识库,答不上 / 答错 / 答案过时 / 两处说法冲突,原来**没有地方收**:
检索记录和 1–5 分评分在 AI 管理后台(8801)那边,而那边**没有维护人、没有「改到了哪一版」、
没有拿原问题复验**;零命中的那次,门店这边连记录编号都没给员工,所以连分都评不了。

这一层只做门店这一侧:

    门店检索记录(kb_rag_record)    一次 kb_rag 一行,编号就是管理后台给的 `试跑id`
      ├ 员工(提问人本人)        提问题类型:答不上 / 答错 / 过期 / 冲突 / 其他 —— 要写说明
      └ 总部运营                  指定维护人、改处理状态(待处理 / 处理中 / 已修订 / 不处理)、
                                  写修订到的知识版本或修订说明 —— 都要写理由
    改动日志(kb_rag_record_log)  每一次改动连同理由、署名,只增不改
    复验存档(kb_recheck)          tools/kb_recheck.py 拿原问题按现在的知识重跑**检索**的前后对比

## 三条硬规矩(写口里拦,不靠页面自觉)

  · 身份只从登录会话来;**只有总部运营能指定维护人、改状态**
  · 提问题类型只认**提问人本人或总部运营** —— 别人的检索记录不归你报
  · 每次改动都要理由,记进日志

## ⚠️ 复验证明不了「答对了」

复验只重跑**检索**(不调大模型生成答案),它能证明的只有「现在找得到相关片段了」。
找到了片段、答案仍可能是错的 —— **仍要人评**。所以复验结论只有三种说法
(`复验结论们`),一个都不许写成「答对了 / 改好了」;`kb_issue_check` 盯这一条。
"""
import json
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DB = os.path.join(HERE, "lanxiu.db")

问题类型们 = ("答不上", "答错", "过期", "冲突", "其他")
处理状态们 = ("待处理", "处理中", "已修订", "不处理")
可处理角色 = ("总部运营",)
# 低分线:卡片原话「低分(≤2)」—— 用户 10-23 拍过的卡片数,不是这里新定的
低分线 = 2
复验结论们 = ("找到了相关片段", "仍然零命中", "复验没跑成")
不等于答对 = ("⚠️ 复验只重跑了检索,没有生成答案:「找到了相关片段」**不等于答对了**,"
          "答得对不对仍要人评。")


def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def _连(db=None):
    c = sqlite3.connect(db or DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS kb_rag_record(
        run_id TEXT PRIMARY KEY,          -- 管理后台给的 试跑id(零命中也有)
        question TEXT NOT NULL, hit INTEGER NOT NULL DEFAULT 0,
        sources TEXT,                     -- 当时选中的出处们(JSON 清单)—— 快照,复验拿它比
        kb_name TEXT,
        asker_no TEXT, asker_name TEXT, asker_role TEXT, created TEXT,
        rating INTEGER, rated_at TEXT,
        issue_type TEXT, issue_note TEXT, issue_by TEXT, issue_at TEXT,
        maintainer_no TEXT, maintainer_name TEXT,
        status TEXT,                      -- 没人提问题类型之前是空:那只是一条检索记录,不是问题
        revised_version TEXT, revised_note TEXT,
        updated TEXT, updated_by TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS kb_rag_record_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, what TEXT NOT NULL,
        before TEXT, after TEXT, why TEXT, by_no TEXT, by_name TEXT, at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS kb_recheck(
        id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, run_id TEXT NOT NULL,
        why_selected TEXT, question TEXT,
        before_hit INTEGER, before_sources TEXT,
        after_hit INTEGER, after_sources TEXT, after_run_id TEXT,
        verdict TEXT, error TEXT, at TEXT)""")


def _日志(c, rid, 什么, 前, 后, 为什么, 我):
    c.execute("INSERT INTO kb_rag_record_log(run_id,what,before,after,why,by_no,by_name,at) VALUES(?,?,?,?,?,?,?,?)",
              (rid, 什么, "" if 前 is None else str(前), "" if 后 is None else str(后),
               (为什么 or "").strip(), (我 or {}).get("no"), (我 or {}).get("name"), _now()))


def _行(c, rid):
    r = c.execute("SELECT * FROM kb_rag_record WHERE run_id=?", (rid,)).fetchone()
    return dict(r) if r else None


def _要登录(我):
    if not 我 or not 我.get("no"):
        return "没登录 —— 要登录,署名用登录的人"
    return None


# ── 记录(chat 那一轮跑完,由智能运维平台转过来)────────────────────────
def 记检索(记录们, 我, db=None):
    """一轮里 kb_rag 的真返回值 → 门店检索记录。提问人 = 登录的人(不读请求体里的)。
    同一个编号只记一次(INSERT OR IGNORE)—— 别人不能拿同一个编号把记录改写成自己的。"""
    e = _要登录(我)
    if e:
        return dict(ok=False, reason=e)
    n = 0
    with closing(_连(db)) as c:
        确保表(c)
        for x in 记录们 or []:
            rid = str((x or {}).get("试跑id") or "").strip()
            q = str((x or {}).get("问的是") or "").strip()
            if not rid or not q:
                continue
            出处 = [str(s) for s in ((x or {}).get("出处们") or [])][:20]
            cur = c.execute("""INSERT OR IGNORE INTO kb_rag_record(run_id,question,hit,sources,kb_name,
                               asker_no,asker_name,asker_role,created) VALUES(?,?,?,?,?,?,?,?,?)""",
                            (rid, q[:500], int((x or {}).get("hit") or 0), json.dumps(出处, ensure_ascii=False),
                             (x or {}).get("知识库"), 我["no"], 我.get("name"), 我.get("role"), _now()))
            n += cur.rowcount
        c.commit()
    return dict(ok=True, 记了=n)


def _本人或总部(r, 我):
    return 我.get("role") in 可处理角色 or r.get("asker_no") == 我.get("no")


def 记评分(rid, 分, 我, db=None):
    """顾问在 chat 里点的 1–5 分,门店这边留一份(复验挑低分要用)。分数的正本仍在管理后台。"""
    e = _要登录(我)
    if e:
        return dict(ok=False, reason=e)
    if not isinstance(分, int) or not (1 <= 分 <= 5):
        return dict(ok=False, reason=f"评分要是 1-5,给的是 {分!r}")
    with closing(_连(db)) as c:
        确保表(c)
        r = _行(c, rid)
        if not r:
            return dict(ok=False, reason=f"门店这边没有这条检索记录:{rid}")
        if not _本人或总部(r, 我):
            return dict(ok=False, reason="这条检索记录不是你问的 —— 只有提问人本人或总部运营能评")
        c.execute("UPDATE kb_rag_record SET rating=?, rated_at=? WHERE run_id=?", (分, _now(), rid))
        _日志(c, rid, "评分", r.get("rating"), 分, "", 我)
        c.commit()
    return dict(ok=True)


# ── 提问题类型(员工本人 / 总部运营)──────────────────────────────────────
def 提类型(rid, 类型, 说明, 我, db=None):
    e = _要登录(我)
    if e:
        return dict(ok=False, reason=e)
    if 类型 not in 问题类型们:
        return dict(ok=False, reason=f"问题类型只能是 {' / '.join(问题类型们)}")
    if not (说明 or "").strip():
        return dict(ok=False, reason="要写一句说明 —— 哪儿答不上 / 错在哪 / 过期成了什么样,维护人要照着改")
    with closing(_连(db)) as c:
        确保表(c)
        r = _行(c, rid)
        if not r:
            return dict(ok=False, reason=f"门店这边没有这条检索记录:{rid}")
        if not _本人或总部(r, 我):
            return dict(ok=False, reason="这条检索记录不是你问的 —— 只有提问人本人或总部运营能报问题")
        状态 = r.get("status") or "待处理"
        c.execute("""UPDATE kb_rag_record SET issue_type=?, issue_note=?, issue_by=?, issue_at=?, status=?,
                     updated=?, updated_by=? WHERE run_id=?""",
                  (类型, 说明.strip()[:500], 我.get("name"), _now(), 状态, _now(), 我.get("name"), rid))
        _日志(c, rid, "问题类型", r.get("issue_type"), 类型, 说明, 我)
        if not r.get("status"):
            _日志(c, rid, "状态", "", 状态, "提了问题类型,进待处理", 我)
        c.commit()
    return dict(ok=True, 状态=状态)


# ── 总部运营:指定维护人、改状态 ────────────────────────────────────────
def _闸(我):
    e = _要登录(我)
    if e:
        return e
    if 我.get("role") not in 可处理角色:
        return f"只有{'/'.join(可处理角色)}能指定维护人、改处理状态,你是{我.get('role')}"
    return None


def 指定维护人(rid, 工号, 理由, 我, db=None):
    e = _闸(我)
    if e:
        return dict(ok=False, reason=e)
    if not (理由 or "").strip():
        return dict(ok=False, reason="指定维护人要写理由 —— 以后有人问「这条为什么归他」,答案在这里")
    with closing(_连(db)) as c:
        确保表(c)
        r = _行(c, rid)
        if not r:
            return dict(ok=False, reason=f"门店这边没有这条检索记录:{rid}")
        if not r.get("issue_type"):
            return dict(ok=False, reason="这条还没人提问题类型 —— 先提类型,才是一条要处理的问题")
        s = c.execute("SELECT no,name FROM staff WHERE no=? AND status='启用'", (工号,)).fetchone()
        if not s:
            return dict(ok=False, reason=f"没有这个在职员工:{工号}")
        c.execute("UPDATE kb_rag_record SET maintainer_no=?, maintainer_name=?, updated=?, updated_by=? WHERE run_id=?",
                  (s["no"], s["name"], _now(), 我.get("name"), rid))
        _日志(c, rid, "维护人", r.get("maintainer_name") or "", s["name"], 理由, 我)
        c.commit()
    return dict(ok=True, 维护人=s["name"])


def 改状态(rid, 到, 理由, 我, 修订版本=None, 修订说明=None, db=None):
    e = _闸(我)
    if e:
        return dict(ok=False, reason=e)
    if 到 not in 处理状态们:
        return dict(ok=False, reason=f"处理状态只能是 {' / '.join(处理状态们)}")
    if not (理由 or "").strip():
        return dict(ok=False, reason="改状态要写理由 —— 以后有人问「这条为什么关了 / 为什么不处理」,答案在这里")
    版 = (修订版本 or "").strip()
    述 = (修订说明 or "").strip()
    # ⚠️ 版本号**不许整串长得像日期**(数据工厂 10-23 提醒):这一栏登记了「文字里不挪」,
    # 但每日平移对 `2026-10-23.1` 这种「日期后紧跟 .数字」才认得出是版本号;光秃秃的 `2026-10-23`
    # 和一个日期一模一样,结构上救不了。照报告口径版本那次的做法:用点分隔(2026.10.23.1)
    import re as _re
    if _re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", 版):
        return dict(ok=False, reason=f"修订版本「{版}」整串是个日期,会被每日平移当成日期挪走 —— 写成点分隔,比如 {版.replace('-', '.')}.1")
    with closing(_连(db)) as c:
        确保表(c)
        r = _行(c, rid)
        if not r:
            return dict(ok=False, reason=f"门店这边没有这条检索记录:{rid}")
        if not r.get("issue_type"):
            return dict(ok=False, reason="这条还没人提问题类型 —— 先提类型,才是一条要处理的问题")
        if 到 == r.get("status") and not (版 or 述):
            return dict(ok=False, reason=f"已经是「{到}」了")
        # 没人认领的「处理中 / 已修订」就是卡片说的那种没人管的待办 —— 先指定维护人
        if 到 in ("处理中", "已修订") and not r.get("maintainer_no"):
            return dict(ok=False, reason=f"还没指定维护人,不能改成「{到}」 —— 没人认领的队列会变成没人管的待办")
        if 到 == "已修订" and not (版 or 述 or r.get("revised_version") or r.get("revised_note")):
            return dict(ok=False, reason="改成「已修订」要写修订到的知识版本或修订说明 —— 复验和以后追查都要知道改到了哪儿")
        c.execute("UPDATE kb_rag_record SET status=?, updated=?, updated_by=? WHERE run_id=?",
                  (到, _now(), 我.get("name"), rid))
        if 到 != r.get("status"):
            _日志(c, rid, "状态", r.get("status"), 到, 理由, 我)
        if 版 and 版 != (r.get("revised_version") or ""):
            c.execute("UPDATE kb_rag_record SET revised_version=? WHERE run_id=?", (版[:200], rid))
            _日志(c, rid, "修订版本", r.get("revised_version"), 版, 理由, 我)
        if 述 and 述 != (r.get("revised_note") or ""):
            c.execute("UPDATE kb_rag_record SET revised_note=? WHERE run_id=?", (述[:500], rid))
            _日志(c, rid, "修订说明", r.get("revised_note"), 述, 理由, 我)
        c.commit()
    return dict(ok=True, 从=r.get("status"), 到=到)


# ── 读 ──────────────────────────────────────────────────────────────
def _出(r):
    d = dict(r)
    try:
        d["sources"] = json.loads(d.get("sources") or "[]")
    except ValueError:
        d["sources"] = []
    return d


def 清单(我, 状态=None, 类型=None, 范围="有问题", db=None):
    """范围:有问题(提过类型的)/ 全部检索记录。非总部运营只看得到自己问的。"""
    e = _要登录(我)
    if e:
        return dict(error=e)
    sql, 参 = "SELECT * FROM kb_rag_record WHERE 1=1", []
    if 范围 != "全部":
        sql += " AND issue_type IS NOT NULL"
    if 状态:
        sql += " AND status=?"; 参.append(状态)
    if 类型:
        sql += " AND issue_type=?"; 参.append(类型)
    if 我.get("role") not in 可处理角色:
        sql += " AND asker_no=?"; 参.append(我["no"])
    with closing(_连(db)) as c:
        确保表(c)
        rows = [_出(r) for r in c.execute(sql + " ORDER BY created DESC LIMIT 500", 参)]
        数 = {k: v for k, v in c.execute(
            "SELECT status, count(*) FROM kb_rag_record WHERE issue_type IS NOT NULL GROUP BY status")}
    return dict(rows=rows, 状态们=list(处理状态们), 类型们=list(问题类型们), 各状态=数,
                能处理=我.get("role") in 可处理角色)


def 详情(rid, 我, db=None):
    e = _要登录(我)
    if e:
        return dict(error=e)
    with closing(_连(db)) as c:
        确保表(c)
        r = _行(c, rid)
        if not r:
            return dict(error=f"没有这条检索记录:{rid}")
        if not _本人或总部(r, 我):
            return dict(error="这条检索记录不是你问的")
        日志 = [dict(x) for x in c.execute(
            "SELECT what,before,after,why,by_name,at FROM kb_rag_record_log WHERE run_id=? ORDER BY id DESC", (rid,))]
        复验 = [dict(x) for x in c.execute(
            "SELECT * FROM kb_recheck WHERE run_id=? ORDER BY id DESC LIMIT 20", (rid,))]
        人 = [dict(x) for x in c.execute(
            "SELECT no,name,role FROM staff WHERE status='启用' ORDER BY role, no")] if 我.get("role") in 可处理角色 else []
    for x in 复验:
        for k in ("before_sources", "after_sources"):
            try:
                x[k] = json.loads(x[k] or "[]")
            except ValueError:
                x[k] = []
    return dict(记录=_出(r), 日志=日志, 复验=复验, 复验声明=不等于答对, 可选维护人=人,
                状态们=list(处理状态们), 类型们=list(问题类型们), 能处理=我.get("role") in 可处理角色)


# ── 复验(tools/kb_recheck.py 用)──────────────────────────────────────
def 复验对象(db=None, 只=None):
    """→ [(记录, 为什么挑它)]。挑三种:标了「已修订」的、低分(≤低分线)的、门店侧看得到的「证据不够」
    —— 检索零命中(chat 这条路只拿证据、不让管理后台生成答案,所以「够不够答」那一栏门店这边没有,
    零命中是这边唯一看得到的证据不够)。"""
    with closing(_连(db)) as c:
        确保表(c)
        出 = []
        for r in c.execute("SELECT * FROM kb_rag_record ORDER BY created"):
            r = dict(r)
            if 只 and r["run_id"] not in 只:
                continue
            为 = []
            if r.get("status") == "已修订":
                为.append("已修订")
            if r.get("rating") is not None and r["rating"] <= 低分线:
                为.append(f"低分({r['rating']} 分)")
            if not r.get("hit"):
                为.append("证据不够(零命中)")
            if 为:
                出.append((_出(r), "、".join(为)))
    return 出


def 记复验(批次, 记录, 为什么, 新, db=None):
    """新 = kb_rag 的返回值(或异常时的 {"error":…})。→ 这一条的结论(三种说法之一)。"""
    if not isinstance(新, dict) or 新.get("error"):
        结论, 新hit, 新出处, 错 = "复验没跑成", None, [], str((新 or {}).get("error") if isinstance(新, dict) else 新)[:300]
    else:
        新hit = int(新.get("hit") or 0)
        新出处 = [str(x.get("出处")) for x in (新.get("证据们") or [])]
        结论, 错 = ("找到了相关片段" if 新hit else "仍然零命中"), None
    assert 结论 in 复验结论们
    with closing(_连(db)) as c:
        确保表(c)
        c.execute("""INSERT INTO kb_recheck(batch,run_id,why_selected,question,before_hit,before_sources,
                     after_hit,after_sources,after_run_id,verdict,error,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (批次, 记录["run_id"], 为什么, 记录["question"], 记录.get("hit"),
                   json.dumps(记录.get("sources") or [], ensure_ascii=False), 新hit,
                   json.dumps(新出处, ensure_ascii=False),
                   (新.get("试跑id") if isinstance(新, dict) else None), 结论, 错, _now()))
        c.commit()
    return dict(结论=结论, 原来几段=记录.get("hit"), 现在几段=新hit,
                新出现的出处=[x for x in 新出处 if x not in (记录.get("sources") or [])],
                # 没跑成时不比:那次什么都没拿到,不是「原来的出处都不见了」
                不见了的出处=([] if 错 else [x for x in (记录.get("sources") or []) if x not in 新出处]), 错=错)
