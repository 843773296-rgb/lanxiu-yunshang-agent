# -*- coding: utf-8 -*-
"""报价的写口 —— 落一次报价 / 作废一条报价。

口径在 `knowledge/quote.py`(业务 2026-09-27 拍了两条:报价是事件、算错了作废不改)。

## 这个文件为什么不是一个 MCP 工具

`intent/scheme-as-unit.md` 里业务 2026-09-18 定的规矩:
> **MCP 跟表走、跟 API 走,场景该由 Skill 编排,不该由 MCP 增生。**

报价是 `quote` skill 编排出来的一整套动作(查五样 → 按八段写 → 发出去),
**落库只是它最后一步的副作用**。所以这里提供的是给页面和 skill 调的写口,
**不新开 `create_quote` 这种动词工具**。
读那一侧才是工具(`get_scheme` 已经在,报价跟着方案一起返回)。

## 谁能写

顾问和店长(`导购角色`)。**经手人就是登录的人,不收工号参数** ——
和 `pickup_write` / `repair_write` 一个做法:收工号参数就等于允许「替别人报价」,
而报价是要对客户负责的东西。

## 时间一律用世界时钟

`quoted_at` / `voided_at` 会被 `tools/shift_world.py` 平移(它是扫列的),
所以必须用 `worldclock.当下()`。判据就是 worldclock 文档里那句:
**这一列会不会被平移** —— 会的话就必须用世界时钟写。
⚠️ 两列都已登记进 `worldclock.已发生的时间列`(C4 和平移前置闸共用那份清单)。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
from oplog import log_op
import worldclock
import quote as Q

导购角色 = ("顾问", "店长")


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _now():
    """**世界的当下**,不是机器时钟 —— `quoted_at` / `voided_at` 都会被平移。"""
    return worldclock.当下().strftime("%Y-%m-%d %H:%M")


def _deny(me, code, reason, key="—"):
    log_op((me or {}).get("name") or "未登录", "quote", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def _方案(scheme_id):
    r = rows("SELECT id,customer_id,status,name FROM scheme WHERE id=?", (scheme_id or "").strip())
    return r[0] if r else None


def 这个方案的报价(scheme_id):
    """按口径模块吃的字段名返回 —— **列名翻一次,只翻在这里**。

    ⚠️ 库里是英文列名(`quoted_at` / `material_cost`),口径模块用的是中文键。
    翻译只放一处:抄两份的话,哪天加一列就会有一处漏掉,
    而漏掉的表现是「那一样永远算缺项」——**看起来像数据没填,其实是翻译漏了**。
    """
    return [dict(id=r["id"], 报于=r["quoted_at"], 物料成本=r["material_cost"],
                 工期区间=r["lead_time"], 可行性=r["feasible"], 尺码=r["size_no"],
                 现货=r["stock"], 作废于=r["voided_at"], 作废原因=r["void_reason"],
                 出具人=r["advisor_no"], 摘要=r["note"])
            for r in rows("SELECT * FROM quote WHERE scheme_id=? ORDER BY quoted_at", scheme_id)]


def 落一次报价(d, me):
    """`quote` skill 出完单之后调这个,把那五样落成一行。

    d: {scheme_id, 物料成本, 工期区间, 可行性, 尺码, 现货, 摘要?}
    """
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return _deny(me, "ROLE", f"报价须由顾问或店长出,你是「{me.get('role')}」")
    s = _方案(d.get("scheme_id"))
    if not s:
        return dict(ok=False, code="NO_SCHEME", reason=f"没有方案 {d.get('scheme_id')}")
    if s["status"] in Q.不作数的方案状态:
        return dict(ok=False, code="SCHEME_DEAD",
                    reason=f"这份方案已经「{s['status']}」—— 给失效的方案报价没有意义,"
                           f"它上面的报价一律不作数。先确认客户说的是哪一份")
    能, 话 = Q.能不能出单(d)
    if not 能:
        return dict(ok=False, code="NOT_READY", reason=话)
    # ⚠️ 上面那道闸之后**再兜一层**:缺项一律不进 SQL。
    # 咬合抓到的:把上面那道闸短路掉之后,`d["物料成本"]` 直接 KeyError ——
    # **写口崩了,而不是拒了**。退出码都是非 0,但「崩了」和「判错了」是两件事:
    # 崩的那一下不会留台账、不会告诉调用方缺了什么,
    # 而咬合第三关问的正是「红的是不是那一条」(那次它答不出来)。
    缺 = [k for k in Q.必须齐的 if d.get(k) is None or d.get(k) == ""]
    if 缺:
        return dict(ok=False, code="NOT_READY",
                    reason=f"还差 {len(缺)} 样:{'、'.join(缺)}(写口兜底拦下的)")
    now = _now()
    # ⚠️ **报价号要对「同一分钟报两次」也成立。**
    # 第一版是 `方案号 + 时间到分钟`,写口检查一跑就撞主键 —— 而世界时钟只到分钟。
    # 这里主键冲突**恰好帮了忙**(它炸了)。但要是当初写的是 `INSERT OR REPLACE`,
    # 它会**静默覆盖上一条** —— 那就把业务刚拍的「报价是事件、一次一行、永不覆盖」
    # 悄悄废掉了,**而且不报错**。
    # 所以序号从库里现数:同一个方案已经有几条,下一条就是几号。
    戳 = now.replace("-", "").replace(" ", "").replace(":", "")
    with sqlite3.connect(DB) as c:
        序 = c.execute("SELECT COUNT(*) FROM quote WHERE scheme_id=?", (s["id"],)).fetchone()[0] + 1
    qid = f"Q{s['id']}-{戳}-{序:02d}"
    # ⚠️ 取值一律用 `.get()`,**缺了就拒,不崩**。
    # 咬合逼出来的:把上面两道闸都拆掉之后,`d["物料成本"]` 直接 KeyError ——
    # 退出码一样是非 0,但**「崩了」和「拒了」是两件事**:崩的那一下不留台账、
    # 不告诉调用方缺了什么,而咬合第三关问的正是「红的是不是那一条」。
    # 换句话说:**真正承重的是取值这一行**,所以它自己也得顶得住。
    try:
        值 = (float(d.get("物料成本")), str(d.get("工期区间")), d.get("可行性"),
              str(d.get("尺码")), str(d.get("现货")))
    except (TypeError, ValueError) as e:
        return dict(ok=False, code="NOT_READY",
                    reason=f"五样里有取不到值的({type(e).__name__})—— "
                           f"**缺项不许进 SQL**,缺一样就不落库")
    with sqlite3.connect(DB) as c:
        c.execute("""INSERT INTO quote(id,scheme_id,customer_id,quoted_at,advisor_no,
                        material_cost,lead_time,feasible,size_no,stock,note)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (qid, s["id"], s["customer_id"], now, me.get("no"), *值,
                   (d.get("摘要") or None)))
    log_op(me.get("name"), "quote", qid, "—", "已报价", True, "QUOTED",
           f"方案 {s['id']} 物料成本 ¥{float(d['物料成本']):.2f}", {"role": me.get("role")})
    全 = 这个方案的报价(s["id"])
    _, 哪条话 = Q.作数的那条(全, s["status"])
    出 = dict(ok=True, code="QUOTED", 报价号=qid, 方案=s["id"], 报于=now, reason=话,
              这份方案的报价情况=哪条话)
    变 = Q.价变了多少(全)
    if 变:
        # **把变化摆出来,不判合不合理** —— 顾问要能回答客户「为什么和上次不一样」
        出["和上次比"] = [x[3] for x in 变[-2:]]
    return 出


def 作废一条报价(d, me):
    """算错了。**作废留痕,不改不删**(业务 2026-09-27)。

    d: {报价号, 原因}
    """
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return _deny(me, "ROLE", f"作废报价须由顾问或店长操作,你是「{me.get('role')}」")
    qid = str(d.get("报价号") or "").strip()
    r = rows("SELECT * FROM quote WHERE id=?", qid)
    if not r:
        return dict(ok=False, code="NO_QUOTE", reason=f"没有报价 {qid}")
    条 = dict(作废于=r[0]["voided_at"], 作废原因=r[0]["void_reason"])
    能, 话 = Q.能不能作废(条, d.get("原因"))
    if not 能:
        return dict(ok=False, code="CANNOT_VOID", reason=话)
    now = _now()
    with sqlite3.connect(DB) as c:
        n = c.execute("UPDATE quote SET voided_at=?, void_reason=?, voided_by=? "
                      "WHERE id=? AND voided_at IS NULL",
                      (now, str(d["原因"]).strip(), me.get("no"), qid)).rowcount
    if n != 1:
        return dict(ok=False, code="RACE", reason="这条报价刚被别人作废了,请刷新再看")
    log_op(me.get("name"), "quote", qid, "已报价", "已作废", True, "QUOTE_VOIDED",
           str(d["原因"]).strip()[:120], {"role": me.get("role")})
    s = _方案(r[0]["scheme_id"])
    _, 哪条话 = Q.作数的那条(这个方案的报价(r[0]["scheme_id"]), s["status"] if s else None)
    return dict(ok=True, code="QUOTE_VOIDED", 报价号=qid, 作废于=now,
                reason=f"已作废。⚠️ **作废只对内** —— 客户手里那份不会因此消失,"
                       f"还得跟客户说一声",
                这份方案的报价情况=哪条话)


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 规格在 tools/bite_specs.json,攻击的是 `backend/quote_write_check.py`。
# ⚠️ 「缺一样不许落库」这件事有**三层**各自承重,所以配了两条不同的咬合:
#   ① 口径 `quote.齐不齐()` · ② 写口这一层兜底 · ③ 取值那一行(`.get` + try)
# 只拆一层不会红(另一层接住了)—— 咬合逼出这个结构的过程记在 ③ 那段注释里。
咬合 = [
    ("让 落一次报价() 不查 能不能出单()", "可行性「不可」→ 不出报价单"),
    ("把写口那层「缺项兜底」和口径那层一起去掉", "缺一样 → 不许落库"),
    ("让 落一次报价() 覆盖上一条而不是新插一行", "报两次 = 两行,不覆盖"),
    ("让 作废一条报价() 不要求写原因", "作废不写原因 → 拒"),
    ("让 落一次报价() 给已失效的方案也能报", "已失效的方案 → 不许再报价"),
    ("让 落一次报价() 用机器时钟写 quoted_at", "报价时间用的是世界时钟"),
]
