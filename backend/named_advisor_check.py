# -*- coding: utf-8 -*-
"""客户点名了谁 → 派单建议(W21,用户 11-12 拍第十二条)。

    python3 backend/named_advisor_check.py

验六件事,**夹具全部自己造**(门店里的在职顾问之外,客户 / 排班 / 占用 / 离职和别店的员工都是现造的),
不靠库里碰巧有什么:

    ① 点名的人有空        → 推荐他,理由里写着他(结构:推荐的工号 = 点名工号,点名.可派 = True)
    ② 点名的人那个时段有活 → 返回里有三步(roster.点名的人没空),推荐的不是他
    ③ 点名的人不在班      → 返回里有三步,码带着排班层的原因
    ④ 没点 / 不详          → 和没有这张预约时**一模一样**(原排序不变)
    ⑤ 点名非本店 / 不在职 / 查无此人 → 两个写口(顾客自助 book、后台新建预约)都拒,库里一行没多
    ⑥ named_state 非法值   → 两个写口拒;绕开写口直接 INSERT,库上 CHECK 也挡(合法三态作对照,能写进去)

全程在**库副本**上:先 import 所有写口模块(booking / roster / server / oplog),再 `check_copy.用副本()` ——
之后才 import 的写口不会被切到(记忆里那个坑)。切完再断言一遍每个模块的 DB 都指着副本。

⚠️ ①④ 是靠**对照**才可观测的:点名的那位特意挑「不点名时不会被推荐的人」——
挑到了本来就会被推荐的人,「点名不优先」这一刀砍下去推荐结果不变,判据看不出来(咬合失效 ⑤)。
"""
import datetime
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── 写口先 import,再切库 ───────────────────────────────────────────
import booking, roster, oplog, server   # noqa: E402,F401
import check_copy                       # noqa: E402

DB = check_copy.用副本("named-")
for _m in (booking, roster, oplog, server):
    if os.path.realpath(_m.DB) != os.path.realpath(DB):
        sys.exit(f"❌ 切库没切到 {_m.__name__}.DB = {_m.DB} —— 不往下跑(下面每一步都在写)")

import worldclock   # noqa: E402

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0
样本 = {}

咬合 = [
    ('点名的人有空却不优先(排序键里去掉点名那一层,照旧按接触史 / 负载挑)',
     '点名的人有空 → 推荐他,理由里写着他'),
    ('点名的人在班但那个时段有别的活,不把原因传给 roster.点名的人没空(它只查在不在班,于是判成「直接派给他」)',
     '点名的人那个时段有别的活 → 返回里有三步,推荐的不是他'),
    ('写入口校验点名时不再要求「本店」(别家店的在职顾问也能被点名)',
     '点名非本店 / 不在职 / 查无此人 → 两个写口都拒,库里一行没多'),
]


def ck(名, ok, 细=""):
    global bad
    if not ok:
        bad += 1
    样本[名] = 样本.get(名, 0) + 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}{('  ← ' + 细) if 细 else ''}")


def q(sql, *a):
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def w(sql, *a):
    with closing(sqlite3.connect(DB)) as c, c:
        c.execute(sql, a)


def main():
    print("\n\033[1m▸ 客户点名了谁 → 派单建议(库副本,夹具自造)\033[0m")
    print("  " + "=" * 76)

    # ── 门店:挑一家有 ≥3 位在职顾问、有门店码的店 ───────────────────
    店行 = q("SELECT shop, shop_code, COUNT(*) n FROM staff WHERE role='顾问' AND status='启用' "
            "AND shop_code IS NOT NULL AND shop_code<>'' GROUP BY shop, shop_code HAVING n>=3 "
            "ORDER BY shop LIMIT 1")
    if not 店行:
        print(f"  {R}❌{D} 找不到有 3 位在职顾问的门店 —— 这一节**没验到**,不叫通过"); sys.exit(1)
    店, 码 = 店行[0]["shop"], 店行[0]["shop_code"]
    别店 = q("SELECT shop, shop_code FROM staff WHERE shop_code IS NOT NULL AND shop_code<>'' "
            "AND shop_code<>? LIMIT 1", 码)
    池 = q("SELECT no, name FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? ORDER BY no", 码)
    print(f"  ·  门店 {店}:在职顾问 {len(池)} 人")

    # ── 日子:世界今天 + 120 天那一周的周三(远离现有排班和日程)───────
    d = worldclock.今天() + datetime.timedelta(days=120)
    d = d + datetime.timedelta(days=(2 - d.weekday()) % 7)
    日 = d.isoformat()
    周一 = d - datetime.timedelta(days=d.weekday())
    周 = [(周一 + datetime.timedelta(days=i)).isoformat() for i in range(7)]

    # ── 排班夹具:那一天本店全员已发布全天班,只有 Y 是早班(10–16)────────
    Y = 池[-1]
    w(f"DELETE FROM roster WHERE shop_code=? AND d IN ({','.join('?' * 7)})", 码, *周)
    w(f"DELETE FROM schedule WHERE start_ts >= ? AND start_ts < ?", 周[0], 周[-1] + " 99")
    for p in 池:
        w("INSERT INTO roster(staff_no,d,shift,shop,shop_code,status,created_by,created) "
          "VALUES(?,?,?,?,?,?,?,?)", p["no"], 日, "S1" if p["no"] == Y["no"] else "S3", 店, 码,
          roster.已发布, "check", 日)

    # ── 员工夹具:本店一位离职顾问、别店一位在职顾问 ─────────────────
    离职, 别店人 = "69992101", "69992102"
    w("DELETE FROM staff WHERE no IN (?,?)", 离职, 别店人)
    w("INSERT INTO staff(no,name,role,shop,shop_code,status) VALUES(?,?,?,?,?,?)",
      离职, "检查用离职", "顾问", 店, 码, "停用")
    if 别店:
        w("INSERT INTO staff(no,name,role,shop,shop_code,status) VALUES(?,?,?,?,?,?)",
          别店人, "检查用别店", "顾问", 别店[0]["shop"], 别店[0]["shop_code"], "启用")

    # ── 客户夹具:没有归属顾问 → book() 落进待分配池,才会走 suggest_why ──
    客 = {}
    for i, k in enumerate(("点名有空", "点名有活", "点名不在班", "没点", "不详", "拒")):
        cid, ph = f"FX-W21-{i}", f"1990021{i:04d}"
        w("DELETE FROM customer WHERE id=? OR phone=?", cid, ph)
        w("INSERT INTO customer(id,name,phone,phone_tail,shop,shop_code,advisor_no,archived,created) "
          "VALUES(?,?,?,?,?,?,NULL,0,?)", cid, f"检查客{i}", ph, ph[-4:], 店, 码, worldclock.今天().isoformat())
        客[k] = dict(id=cid, phone=ph)

    def 时段(h):
        return f"{日} {h:02d}:00", f"{日} {h + 1:02d}:00"

    def 基线(k, h):
        a, b = 时段(h)
        return booking.suggest_why(dict(shop=店, customer_id=客[k]["id"], start_ts=a, end_ts=b))

    def 约(k, h, **点):
        r = booking.book(dict(phone=客[k]["phone"], when=时段(h)[0].replace(" ", "T"), need="检查用", **点))
        if not r.get("ok"):
            return r, None
        t = q("SELECT * FROM schedule WHERE id=?", r["task"])[0]
        return r, t

    # ═══ ① 点名的人有空 ═══════════════════════════════════════════
    基, 因 = 基线("点名有空", 11)
    if not 基:
        print(f"  {R}❌{D} 不点名时提不出建议({因})—— 夹具没造对,下面都验不到"); sys.exit(1)
    X = next((p for p in 池 if p["no"] not in (基["no"], Y["no"])), None)
    if not X:
        print(f"  {R}❌{D} 挑不出「不点名时不会被推荐」的顾问 —— ① 不可观测"); sys.exit(1)
    print(f"  ·  对照:不点名时 11 点推荐 {基['name']};点名挑的是 {X['name']}(不点名时不会被推荐的人)")
    r, t = 约("点名有空", 11, named_advisor_no=X["no"], named_state="点名", channel="电话")
    ck("点名有空的那张预约约上了,而且落进待分配池", bool(t) and t["assignee_no"] is None,
       f"{r.get('code')} {r.get('reason', '')}"[:80])
    if t:
        行 = q("SELECT named_advisor_no, named_state, channel FROM appointment WHERE id=?", r["appt"])[0]
        ck("顾客自助预约:点名三列都落库了",
           (行["named_advisor_no"], 行["named_state"], 行["channel"]) == (X["no"], "点名", "电话"), str(行))
        建, 因 = booking.suggest_why(t)
        ck("点名的人有空 → 推荐他,理由里写着他",
           bool(建) and 建["no"] == X["no"] and (建.get("点名") or {}).get("可派") is True
           and X["name"] in 建["why"][0],
           f"推荐 {建 and 建['no']},点名 {X['no']};理由首条:{(建 or {}).get('why', [''])[0][:40]}")

    # ═══ ④ 没点 / 不详 → 原排序不变 ═══════════════════════════════
    for k, 态 in (("没点", "没点"), ("不详", None)):
        前, _ = 基线(k, 11)
        r, t = 约(k, 11, **({"named_state": 态} if 态 else {}))
        if not t:
            ck(f"「{k}」那张预约约上了", False, f"{r.get('code')} {r.get('reason')}"); continue
        存 = q("SELECT named_state FROM appointment WHERE id=?", r["appt"])[0]["named_state"]
        ck(f"「{k}」三态落库是「{k}」(不给就是不详,不猜成没点)", 存 == k, f"存的是 {存}")
        后, _ = booking.suggest_why(t)
        摘 = lambda s: ((s or {}).get("no"), [a["no"] for a in (s or {}).get("alts", [])])
        ck("没点名 → 原排序不变(和没有这张预约时推荐的人、备选顺序都一样)",
           摘(前) == 摘(后) and (后 or {}).get("点名") is None, f"前 {摘(前)} 后 {摘(后)}")

    # ═══ ② 点名的人那个时段有别的活 ═══════════════════════════════
    w("INSERT INTO schedule(id,type,advisor_no,customer_id,start_ts,end_ts,status,shop,shop_code,assignee_no,note) "
      "VALUES('FX-W21-BUSY','接待任务',?,NULL,?,?,'有效',?,?,?,'检查用占用')",
      X["no"], *时段(14), 店, 码, X["no"])
    r, t = 约("点名有活", 14, named_advisor_no=X["no"], named_state="点名")
    if not t:
        ck("点名有活的那张预约约上了", False, f"{r.get('code')} {r.get('reason')}")
    else:
        建, 因 = booking.suggest_why(t)
        点 = (建 or {}).get("点名") or {}
        ck("点名的人那个时段有别的活 → 返回里有三步,推荐的不是他",
           bool(建) and 点.get("可派") is False and str(点.get("码", "")).startswith("REQUESTED_")
           and all(m in (点.get("三步") or "") for m in "①②③") and 建["no"] != X["no"],
           f"推荐 {建 and 建['no']} · 码 {点.get('码')} · 三步 {len(点.get('三步') or '')} 字")

    # ═══ ③ 点名的人不在班(早班的人约到 17 点)═════════════════════
    r, t = 约("点名不在班", 17, named_advisor_no=Y["no"], named_state="点名")
    if not t:
        ck("点名不在班的那张预约约上了", False, f"{r.get('code')} {r.get('reason')}")
    else:
        建, 因 = booking.suggest_why(t)
        点 = (建 or {}).get("点名") or {}
        ck("点名的人不在班 → 返回里有三步(码带排班层的原因),推荐的不是他",
           bool(建) and 点.get("可派") is False and 点.get("码") == "REQUESTED_OUT_OF_SHIFT"
           and all(m in (点.get("三步") or "") for m in "①②③") and 建["no"] != Y["no"],
           f"推荐 {建 and 建['no']} · 码 {点.get('码')}")

    # ═══ ⑤ 点名非本店 / 不在职 / 查无此人 → 两个写口都拒 ═══════════
    坏人 = [("不在职", 离职), ("查无此人", "69992199")] + ([("别店", 别店人)] if 别店 else [])
    if not 别店:
        print(f"  {R}❌{D} 库里只有一家门店有员工 —— 「别店的人不能点」验不到"); globals()["bad"] = bad + 1
    a15, b15 = 时段(15)
    for 类, no in 坏人:
        前 = q("SELECT COUNT(*) n FROM appointment")[0]["n"]
        r1 = booking.book(dict(phone=客["拒"]["phone"], when=a15.replace(" ", "T"),
                               named_advisor_no=no, named_state="点名"))
        r2 = server.create_appointment(dict(customer_id=客["拒"]["id"], start=a15, end=b15, shop=店,
                                            named_advisor_no=no, named_state="点名"), "检查", "店长")
        后 = q("SELECT COUNT(*) n FROM appointment")[0]["n"]
        ck("点名非本店 / 不在职 / 查无此人 → 两个写口都拒,库里一行没多",
           not r1.get("ok") and not r2.get("ok") and r1.get("code") == r2.get("code") == "BAD_NAMED_ADVISOR"
           and 前 == 后, f"{类}:自助 {r1.get('code')} · 后台 {r2.get('code')} 「{(r2.get('reason') or '')[:30]}」")
    # 后台写口的正向对照:本店在职的人能点,三列落库(没有这一条,上面「都拒」也可能是这个口整个坏了)
    r2 = server.create_appointment(dict(customer_id=客["拒"]["id"], start=a15, end=b15, shop=店,
                                        named_advisor_no=X["no"], channel="微信"), "检查", "店长")
    行 = q("SELECT named_advisor_no, named_state, channel FROM appointment WHERE id=?", r2.get("id"))
    ck("后台新建预约:本店在职顾问能点名,不给三态时按点名记,三列落库",
       bool(r2.get("ok")) and bool(行) and (行[0]["named_advisor_no"], 行[0]["named_state"], 行[0]["channel"])
       == (X["no"], "点名", "微信"), f"{r2.get('code')} {行}")

    # ═══ ⑥ named_state 非法值写不进去 ═════════════════════════════
    for 坏态, 点人 in (("是", X["no"]), ("点名", None), ("没点", X["no"])):
        r1 = booking.book(dict(phone=客["拒"]["phone"], when=a15.replace(" ", "T"),
                               named_state=坏态, named_advisor_no=点人))
        r2 = server.create_appointment(dict(customer_id=客["拒"]["id"], start=a15, end=b15, shop=店,
                                            named_state=坏态, named_advisor_no=点人), "检查", "店长")
        ck("非法 / 自相矛盾的点名三态 → 两个写口都拒",
           not r1.get("ok") and not r2.get("ok") and r1.get("code") == r2.get("code")
           and r1.get("code") in ("BAD_NAMED_STATE", "NAMED_NO_ADVISOR", "NAMED_STATE_CONFLICT"),
           f"三态「{坏态}」+ 点名人 {点人}:{r1.get('code')} / {r2.get('code')}")
    # 绕开写口:库上 CHECK 挡。合法三态作对照 —— 对照写不进去的话,「非法值被挡」可能只是别的原因
    for i, 态 in enumerate(booking.点名三态):
        try:
            w("INSERT INTO appointment(id,customer_id,start_ts,end_ts,status,named_state) "
              "VALUES(?,?,?,?,'待确认',?)", f"FX-W21-OK{i}", 客["拒"]["id"], a15, b15, 态)
            ck("对照:合法三态直接 INSERT 写得进去", True, 态)
        except sqlite3.Error as e:
            ck("对照:合法三态直接 INSERT 写得进去", False, f"{态}:{e}")
    try:
        w("INSERT INTO appointment(id,customer_id,start_ts,end_ts,status,named_state) "
          "VALUES('FX-W21-BAD',?,?,?,'待确认','随便')", 客["拒"]["id"], a15, b15)
        ck("绕开写口直接 INSERT 非法三态 → 库上 CHECK 挡住", False, "写进去了 —— 这个库的 named_state 没带 CHECK")
    except sqlite3.IntegrityError as e:
        ck("绕开写口直接 INSERT 非法三态 → 库上 CHECK 挡住", "CHECK" in str(e), str(e)[:60])

    print("\n  样本量:" + ";".join(f"{k[:18]}… {v} 例" for k, v in 样本.items()))
    if bad:
        print(f"\n{R}❌ 点名派单 {bad} 处不符合预期{D}"); sys.exit(1)
    print(f"\n{G}✅ 点名派单全部符合预期{D}(共 {sum(样本.values())} 例)")


if __name__ == "__main__":
    main()
