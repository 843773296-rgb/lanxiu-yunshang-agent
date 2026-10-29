#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评价写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 pickup_write_check)。

钉的几件事(口径在 `knowledge/rating.py`,业务 2026-09-24 / 09-27):
    闸       **没签收不许评**;而且判据是签收记录本身,不是订单状态
    一次     一个包裹一次;手机后四位对不上不许评
    星级     1-5 整数,6 星不夹成 5 星
    差评     ≤3 星**自动进已有的 task 清单**(type='评价差评'),不新建第二张表
    改       24 小时内一次;好评改差评进清单,**差评改好评不撤出**
    处理     只有店长能关,**必须写处理记录**
    不变量   rating 表**没有 status 列**(状态只存 task 上);时间用世界时钟

## 夹具是**跑出来的,不是插进去的**

签收那一步走 `pickup_write` 的真实流程(到店 → 顾客出码 → 导购核验),
不直接 `INSERT pickup_item`。**自己插一条签收记录来测闸,测的就不是闸** ——
插的时候想当然填上的那几列,正好是闸要读的那几列。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("让 customer_rate() 不问签收就收下评价", "没签收 → 不许评"),
    ("把 差评线 从 3 改成 2(3 星就不建工单了)", "3 星是差评 → 自动进 task 清单"),
    ("让 close_bad_rating() 不要求处理记录", "关差评不写处理记录 → 拒"),
    ("让 close_bad_rating() 放开角色(顾问也能关)", "顾问关差评 → 拒"),
    # ⚠️ 这条原来写的是「不要求处理方式(空也放过)」→ 预期红「不给处理方式 → 拒」。
    # 咬合证明那个改法**红不了**:`if not 方式` 那一支是**冗余的** ——
    # 去掉它,空串照样被下一行的枚举检查拦住(它存在的意义是给一句更好的话,不是承重)。
    # 真承重的是枚举那一行,而它破的是「处理方式不在枚举里」那条判据。
    ("让 rating.处理方式能不能用() 不比枚举(空的、乱写的都放过)",
     "处理方式不在枚举里 → 拒"),
    ("让 rating.出钱的处理方式 变成空元组(出钱的也当不出钱)", "出钱却没填批准人 → 拒"),
    ("让 rating.处理方式能不能用() 不比批准人和处理人是不是同一个",
     "批准人填成处理人自己 → 拒"),
    ("让 customer_edit_rating() 在差评改好评时把工单关掉", "差评改好评 → 工单不撤,还在待处理"),
    ("在 seed_rating 的建表里加一句 ALTER,给 rating 加个 status 列",
     "rating 表没有 status 列(状态只存 task 上)"),
    ("把 seed_rating._建() 里的补列去掉", "已有的老表补完列,和从零建的列一致"),
    ("把 worldclock.已发生的时间列 里 rating 那三行去掉",
     "四列时间都登记进了 worldclock.已发生的时间列"),
    # ── 2026-10-14 退款金额 + 超线上升一级 ─────────────────────────────
    ("让 rating.要填金额吗() 对「部分退款」也返回不用填",
     "部分退款**不填金额** → 拒"),
    ("让 rating.处理方式能不能用() 不比金额和订单额",
     "部分退款**退得比订单额多** → 拒"),
    # ⚠️ 2026-10-18:破坏点原来是「把线调到一个超大的数」,**而那条咬合永远红不了** ——
    # 夹具挑单(`o.amount > _线`)和用例金额(`_线 + 1`)**都跟着这条线漂**,
    # 线一变大,挑不到单、金额也跟着超过订单额,拒是拒了、拒的理由全换了。
    # **破坏一个量的时候,别让夹具也靠这个量算出来。**
    ("让 rating.这笔要谁批() 对超线的金额也返回「不限角色」(等于这道闸没有)",
     "→ 拒(角色也是从库里现读的)"),
    ("让 rating_write 从调用方传的 amount 里取订单额,而不是从库里现读",
     "全额退款**自己填了别的数** → 拒(金额就是订单额,系统现算)"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:150]) if extra else ''}")
    if not ok: FAIL.append(name)


def 拒在(结果, 码, 理由里有):
    """拒了,**而且拒的是那一条** —— 返回 (成立吗, 实际是什么)。

    ⚠️⚠️ **为什么非要连理由一起断言。** `close_bad_rating` 的拒绝码**只有一个
    `NEED_WAY`**,它把六七条不同的规则压成同一个值:没选处理方式 / 不在枚举里 /
    出钱没填批准人 / 批准人是处理人自己 / 该填金额没填 / 退得比订单额多 /
    全额退款自己填了别的数 / 超线没有上一级批。
    > **一条「双人复核拦住了」和一条「金额没填被拦住」,在那个 `NEED_WAY` 上
    > 长得一模一样。**

    2026-10-21 夜咬合逮到三条判据正是这么测错的 —— 而其中一条的根因是
    **夹具靠的那个订单额跟着库重建漂了**(9649 → 24632),一越过 10000 那条线,
    拒的理由就整条换掉,而判据照样绿。
    只断言 code 的话,下一次漂过某条线时**没有任何信号**;连理由一起断言,
    漂的那一下红的是判据本身。
    """
    码实 = (结果 or {}).get("code")
    话 = str((结果 or {}).get("reason") or "")
    return (码实 == 码 and 理由里有 in 话), f"code={码实} reason={话[:70]}"


def main():
    print("评价写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 88)
    tmp = tempfile.mkdtemp(prefix="ratew-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 评价写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 评价写口 {N[0]} 条全过\033[0m")


def run(T):
    import oplog, pickup_write as pw, rating_write as rt, repair_write as rw, seed_rating
    import rating as R, worldclock
    for m in (oplog, pw, rt, rw): m.DB = T
    seed_rating.建表(T)
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row

    # ── 不变量:状态只存一处 ──────────────────────────────────────────
    列 = [r["name"] for r in c.execute("PRAGMA table_info(rating)")]
    ck("库里有评价表", bool(列))
    # ⚠️ 老库**自己造**,不拿真库副本当老库:真库补过列之后,拿它验「补列」永远是绿的 ——
    # 咬合改坏 `_补列` 也红不了(破坏点不可观测)。
    # 崩了也算**这一条**红 —— 不让一个异常把整份检查带崩、后面该红的那条没机会打印
    try:
        _新 = sqlite3.connect(":memory:"); seed_rating.建表(_新)
        _老 = sqlite3.connect(":memory:"); _老.execute("CREATE TABLE rating(pkg_id TEXT PRIMARY KEY, star INTEGER)")
        seed_rating.建表(_老); seed_rating.建表(_老)      # 跑两遍:补过的不许再补
        _新列 = [r[1] for r in _新.execute("PRAGMA table_info(rating)")]
        _老列 = [r[1] for r in _老.execute("PRAGMA table_info(rating)")]
        _对, _说 = sorted(_老列) == sorted(_新列), f"老表 {len(_老列)} 列、新表 {len(_新列)} 列,差 {sorted(set(_新列) ^ set(_老列))}"
    except Exception as e:
        _对, _说 = False, f"补列时崩了:{type(e).__name__}: {e}"
    ck("已有的老表补完列,和从零建的列一致(分项/标签/媒体/匿名/追评)", _对,
       _说 + " —— `CREATE TABLE IF NOT EXISTS` 在已有的库上什么都不做,新列只会出现在从零重建的库里")
    ck("rating 表没有 status 列(状态只存 task 上)", "status" not in 列,
       "两处都存的话,「工单关了但评价那行还是待处理」这种漂**不会报错**,只会让两个页面显示不同的东西")
    ck("四列时间都登记进了 worldclock.已发生的时间列(C4 和平移闸都读它)",
       {("rating", "rated_at"), ("rating", "edited_at"), ("rating", "handled_at"), ("rating", "followup_at")}
       <= {(t, col) for t, col, _, _ in worldclock.已发生的时间列},
       "不登记就是两道闸同时的盲区 —— pkg.created 上次就是这么漏的")

    # ── 夹具:**把签收真的跑出来**,不插 pickup_item ────────────────────
    o = c.execute("""SELECT o.id, o.shop, o.customer_id, k.phone_tail FROM ordr o
                       JOIN customer k ON k.id=o.customer_id
                      WHERE o.kind='定制品订单' AND o.status='已发货'
                        AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                        AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                      ORDER BY o.id LIMIT 1""").fetchone()
    ck("有一张已发货、一个包裹、还没到店的定制单当夹具", bool(o))
    if not o: return
    oid, 尾 = o["id"], o["phone_tail"]
    人 = lambda role, 店: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' AND shop=? ORDER BY no LIMIT 1",
        (role, 店)).fetchone())
    顾问, 店长 = 人("顾问", o["shop"]), 人("店长", o["shop"])
    ck("本店有顾问也有店长", bool(顾问) and bool(店长))
    if not (顾问 and 店长): return

    # ── 闸:**签收之前**一律不许评 ────────────────────────────────────
    包 = c.execute("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL", (oid,)).fetchone()["pkg_id"]
    # ⚠️ 基线**取当前行数**,不假设「表是空的」。
    # 2026-09-27 踩到:这两条原来写的是 `COUNT(*) FROM rating == 0` ——
    # 那天铺了 1646 条演示评价,检查当场红。
    # **它依赖的是「这张表恰好还没造数」这个偶然事实**,而那种依赖
    # 在造数那天才会暴露,看起来像功能坏了。判据该问的是
    # 「**这一次被拒之后有没有多出来一行**」,不是「全表是不是空的」。
    基线 = c.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
    没多 = lambda: c.execute("SELECT COUNT(*) FROM rating").fetchone()[0] == 基线
    r = rt.customer_rate(oid, 尾, 5, "很好", pkg=包)
    ck("没签收 → 不许评", not r["ok"] and r["code"] == "CANNOT_RATE", r.get("reason"))
    ck("被拒的时候一行都没写进去", 没多(), f"基线 {基线} 条")

    # 走真实签收流程:到店 → 顾客出码 → 导购核验
    pw.arrive({"order_id": oid}, 顾问)
    码 = pw.customer_issue_code(oid, 尾).get("试穿合身码")
    v = pw.verify({"order_id": oid, "code": 码}, 顾问)
    ck("签收流程跑通了(到店 → 出码 → 核验)", v.get("ok"), v.get("reason"))
    ck("签收留下了「件」上的记录(闸读的就是它)",
       c.execute("SELECT COUNT(*) FROM pickup_item WHERE pkg_id=? AND fit_result='合身' AND fit_at IS NOT NULL",
                 (包,)).fetchone()[0] > 0)

    # ── 签收之后:能评 ────────────────────────────────────────────────
    ck("手机后四位对不上 → 不许评",
       rt.customer_rate(oid, "0000" if 尾 != "0000" else "1111", 5)["code"] == "NOT_YOURS")
    ck("6 星 → 拒,而且不夹成 5 星", rt.customer_rate(oid, 尾, 6)["code"] == "BAD_STAR")
    ck("0 星 → 拒", rt.customer_rate(oid, 尾, 0)["code"] == "BAD_STAR")
    ck("半星 → 拒", rt.customer_rate(oid, 尾, 4.5)["code"] == "BAD_STAR")
    ck("还是一行都没写进去(被拒的都没落库)", 没多(), f"基线 {基线} 条")
    r = rt.customer_rate(oid, 尾, 5, "导购很细心")
    ck("签收之后 5 星 → 收下", r["ok"], r.get("reason"))
    行 = c.execute("SELECT * FROM rating WHERE pkg_id=?", (包,)).fetchone()
    ck("评价落在包裹上,带着单号和客户", 行 and 行["order_id"] == oid and 行["customer_id"] == o["customer_id"])
    ck("来源记的是顾客小程序(顾问不能替顾客评)", 行["src"] == rt.来源_顾客)
    ck("经手顾问记下来了(店长要能查是谁经手的,但不进考核)", 行["advisor_no"] == 顾问["no"])
    ck("评价时间用的是**世界时钟**,不是机器时钟",
       str(行["rated_at"])[:10] == worldclock.今天().isoformat(),
       f"写出来是 {行['rated_at']},世界的今天是 {worldclock.今天()}")
    ck("5 星不建工单", 行["task_id"] is None
       and c.execute("SELECT COUNT(*) FROM task WHERE ref_id=?", (包,)).fetchone()[0] == 0)
    ck("同一个包裹再评 → 拒(一个包裹一次)", rt.customer_rate(oid, 尾, 4)["code"] == "CANNOT_RATE")

    # ── 改:好评 → 差评,进清单 ────────────────────────────────────────
    r = rt.customer_edit_rating(oid, 尾, 3, "回家发现袖口线头很多")
    ck("24 小时内能改一次", r["ok"], r.get("reason"))
    ck("好评改差评 → 进清单", r.get("清单") == "进清单", r.get("reason"))
    # ⚠️ 这里故意用 **3 星**:业务 2026-09-27 定的是「≤3 算差评」,不是常见的 ≤2。
    # 第一版这条名字写着「3 星」、改的却是 2 星 —— **名字和它真正测的不是一回事**,
    # 那样把 差评线 从 3 改成 2 也不会红(2 星在两种线下都是差评)。这个坑记在 B-85,这是第三次。
    t = c.execute("SELECT * FROM task WHERE ref_id=?", (包,)).fetchone()
    ck("3 星是差评 → 自动进 task 清单", bool(t) and t["type"] == rt.工单类型 and t["status"] == "待处理",
       dict(t) if t else "没建工单")
    ck("工单进的是**已有的** task 表,没有新建第二张清单表",
       not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name LIKE '%rating%todo%'").fetchone())
    ck("工单号是定的(TR+包裹号,重跑不会重复建)", t["id"] == f"TR{包}")
    ck("再改一次 → 拒(最多改一次)", not rt.customer_edit_rating(oid, 尾, 5)["ok"])

    # ── 店长处理 ─────────────────────────────────────────────────────
    ck("顾问关差评 → 拒", rt.close_bad_rating({"pkg": 包, "note": "已联系顾客并补送"}, 顾问)["code"] == "ROLE")
    ck("没登录 → 拒", rt.close_bad_rating({"pkg": 包, "note": "x" * 10}, None)["code"] == "NO_LOGIN")
    ck("关差评不写处理记录 → 拒", rt.close_bad_rating({"pkg": 包, "note": ""}, 店长)["code"] == "NEED_NOTE")
    ck("「看过了」太短,不算处理完", rt.close_bad_rating({"pkg": 包, "note": "看过了"}, 店长)["code"] == "NEED_NOTE")
    ck("被拒之后工单还在待处理",
       c.execute("SELECT status FROM task WHERE id=?", (t["id"],)).fetchone()[0] == "待处理")
    _单额 = c.execute("SELECT amount FROM ordr WHERE id=?", (oid,)).fetchone()["amount"]
    import rating as _R金
    _线 = _R金.退款上升一级的线
    _要谁 = _R金.上升一级要谁批
    _上级0 = (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no, name, role FROM staff WHERE role=? AND status='启用' LIMIT 1",
        (_要谁,)).fetchone())
    # ── 处理方式 + 出钱要第二个人(业务 2026-10-11)─────────────────────
    # ⚠️ 这几条**先于**成功用例,因为成功用例一关就没法再试拒绝了
    # (关过的工单走 ALREADY_CLOSED,后面那些判据就都测不到了)。
    ck("不给处理方式 → 拒", *拒在(rt.close_bad_rating(
        {"pkg": 包, "note": "已电话联系顾客,约了周六回店修线头,顾客接受"}, 店长),
        "NEED_WAY", "关差评要选处理方式"))
    ck("处理方式不在枚举里 → 拒", *拒在(rt.close_bad_rating(
        {"pkg": 包, "note": "已电话联系顾客,约了周六回店修线头,顾客接受",
         "way": "随便给点什么"}, 店长), "NEED_WAY", "处理方式只能是"))
    ck("出钱却没填批准人 → 拒", *拒在(rt.close_bad_rating(
        {"pkg": 包, "note": "已协商,顾客保留衣服,退还工费部分", "way": "部分退款"},
        店长), "NEED_WAY", "填批准人"))
    # **这一条是双人复核的承重墙**:一个人既处置又批准,记录上两个字段都填着
    # ⚠️ **必须传一个合法金额** —— 不传的话这条拒在「部分退款必须填金额」上,
    # 双人复核那条规则根本没被用到(咬合 2026-10-21 供出来的)。
    # 金额取一个既不超订单额、也不超「上升一级」那条线的数。
    _小额 = min(_单额, _线) / 2.0
    ck("批准人填成处理人自己 → 拒", *拒在(rt.close_bad_rating(
        {"pkg": 包, "note": "已协商,顾客保留衣服,退还工费部分", "way": "部分退款",
         "approved_by": 店长["no"], "amount": _小额}, 店长),
        "NEED_WAY", "批准人填的是处理人自己"))
    # ── 退款金额 + 超线上升一级(用户 2026-10-14 拍「上一级 = 总部运营」)────────
    #
    # ⚠️ 这一组**自己造出它要验的那几种形状**,不靠库里碰巧有什么:
    # 订单额是现读的,所以每条用例的金额都从它算出来。
    #
    # ⚠️ 2026-10-17 并行会话报红逮到:这里原来还有一条「超线要谁批 → 拒」,
    # 用的金额是 `_线 + 1`(10001),**而这张夹具单的订单额只有 9649** ——
    # 于是它**先撞上「退得比收的多」那条规则**(金额校验排在超线判定之前),
    # 拒是拒了,拒的理由跟超线一个字关系都没有。
    # > 一条「超线要上一级批才拦住」和一条「退得比订单额多被拦住」,
    # > **在那个 NEED_WAY 上长得一模一样。**
    # 这比「什么都没验」更糟:它给的是**假证据** —— 让人以为那道闸有咬合护着。
    # 📌 那条已经挪到下面第三张单那段:**那张单是按「订单额超线」挑出来的**,
    #    金额也从它的订单额算,所以「超了线」和「没超单额」能同时成立。
    ck(f"夹具的订单额说得出来({_单额:.2f})—— 下面几条的金额都从它算",
       _单额 is not None and _单额 > 0, _单额)
    # 批准人用**顾问** —— 他不是处理人自己(过得了那道闸),而且不是「上升一级」
    # 要的那个角色(所以超线那条该拒)。⚠️ 跨店角色(总部运营 / 售后)的 `shop` 是空,
    # `人(role, 店)` 按店取**取不到**,所以正向那条另找一个人,见下面第三张单那段。
    #
    # ⚠️⚠️ **2026-10-21 夜:下面有三条判据,拒的理由不是它们声称的那一条。**
    # 咬合把它们供出来了 —— 去掉口径层对应的那一支,**三条照样全绿**。
    # 根因是 `close_bad_rating` 的拒绝码**只有一个 `NEED_WAY`**,
    # 它把六七条不同的规则压成同一个值:
    #   · 「不给处理方式」那一支去掉 → 下一行的**枚举检查**兜住了(空串不在枚举里);
    #   · 「批准人=处理人」那一支去掉 → 夹具**没传金额**,于是被
    #     「部分退款必须填金额」拦下,**双人复核那条规则根本没被用到**;
    #   · 「金额>订单额」那一支去掉 → 夹具金额是 `订单额+1`,而这张单的订单额
    #     **已经从 9649 漂到 24632**,一越过 10000 那条线,拒的理由就换成
    #     「超线要总部运营批」(批准人是顾问,不满足)。
    # > **三条拒的理由都不是它们声称的那条,而它们都返回同一个 `NEED_WAY`。**
    # 这正是这个文件 10-17 为超线那条记过的坑,只是方向反了:
    # 那次是金额跟着「线」漂,这次是**夹具靠的那个订单额跟着重建漂**。
    # 修法是让每条的拒绝理由**唯一**:
    #   · 批准人=处理人那条 → **传上一条合法的金额**(金额那几关都过得去);
    #   · 退超额那条 → 批准人换成**超线那一档要的角色**(超线那关过得去)。
    # ⚠️ 这是**收紧**判据,不是放宽。
    ck("部分退款**不填金额** → 拒", rt.close_bad_rating(
        {"pkg": 包, "note": "已协商,顾客保留衣服,退还工费部分", "way": "部分退款",
         "approved_by": 顾问["no"]}, 店长)["code"] == "NEED_WAY")
    # ⚠️ **批准人换成「上升一级」那一档要的角色** —— 用顾问的话,这条会拒在
    # 「超线要 X 批」上(这张单的订单额已经从 9649 漂到 24632,`订单额+1` 越过了那条线),
    # 而那不是这条判据要验的东西(咬合 2026-10-21 供出来的)。
    ck("部分退款**退得比订单额多** → 拒(订单额是从库里现读的)", *拒在(rt.close_bad_rating(
        {"pkg": 包, "note": "已协商,顾客保留衣服,退还工费部分", "way": "部分退款",
         "approved_by": (_上级0 or 顾问)["no"], "amount": _单额 + 1}, 店长),
        "NEED_WAY", "退得比收的多"))
    ck("不出钱的那几种**填了金额** → 拒(不是忽略)", rt.close_bad_rating(
        {"pkg": 包, "note": "已电话联系顾客,约了周六回店修线头,顾客接受", "way": "免次改衣",
         "amount": 500}, 店长)["code"] == "NEED_WAY")
    ck("全额退款**自己填了别的数** → 拒(金额就是订单额,系统现算)", rt.close_bad_rating(
        {"pkg": 包, "note": "已协商全额退款,衣服回收", "way": "全额退款",
         "approved_by": 顾问["no"], "amount": 1.0}, 店长)["code"] == "NEED_WAY")
    ck("拒了这几次之后工单还在待处理",
       c.execute("SELECT status FROM task WHERE id=?", (t["id"],)).fetchone()[0] == "待处理")

    r = rt.close_bad_rating({"pkg": 包, "note": "已电话联系顾客,约了周六回店修线头,顾客接受",
                             "way": "免次改衣"}, 店长)
    ck("店长写了处理记录 + 给了处理方式 → 关得掉", r["ok"], r.get("reason"))
    ck("不出钱的那档不要批准人", r.get("出钱") is False and r.get("批准人") is None, str(r)[:80])
    ck("工单状态变成已关闭",
       c.execute("SELECT status FROM task WHERE id=?", (t["id"],)).fetchone()[0] == "已关闭")
    ck("处理记录、处理人、**处理方式**都落在评价那行上",
       (lambda x: x["handle_note"] and x["handled_by"] == 店长["no"] and x["handled_at"]
        and x["handle_way"] == "免次改衣")(
           c.execute("SELECT * FROM rating WHERE pkg_id=?", (包,)).fetchone()),
       "← 只落处理记录不落方式,「给没给钱」就还是靠读那段中文判")
    # ⚠️ 这里**必须带上 way** —— 不带的话它会先撞 NEED_WAY,
    # 于是这条判据测到的是「少了参数」,不是「已关闭不能再关」。
    # > 一条「因为已关闭被拒」和一条「因为少参数被拒」,
    # > **在「被拒了」这件事上长得一模一样。**
    ck("已关闭的工单不能再关一次", rt.close_bad_rating(
        {"pkg": 包, "note": "再关一次试试看", "way": "只回访"}, 店长)["code"] == "ALREADY_CLOSED")

    # ── 差评改好评:**工单不撤** ───────────────────────────────────────
    # 另找一个包裹从头走一遍 —— 上面那个已经改过一次了。
    o2 = c.execute("""SELECT o.id, k.phone_tail, o.shop FROM ordr o JOIN customer k ON k.id=o.customer_id
                       WHERE o.kind='定制品订单' AND o.status='已发货' AND o.shop=?
                         AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                         AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                       ORDER BY o.id LIMIT 1""", (o["shop"],)).fetchone()
    ck("有第二张单当夹具", bool(o2))
    if o2:
        oid2, 尾2 = o2["id"], o2["phone_tail"]
        pw.arrive({"order_id": oid2}, 顾问)
        码2 = pw.customer_issue_code(oid2, 尾2).get("试穿合身码")
        pw.verify({"order_id": oid2, "code": 码2}, 顾问)
        包2 = c.execute("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL", (oid2,)).fetchone()["pkg_id"]
        r = rt.customer_rate(oid2, 尾2, 2, "等太久了")
        ck("一上来就 2 星 → 收下并当场进清单", r["ok"] and r.get("差评") and r.get("工单") == f"TR{包2}",
           r.get("reason"))
        r = rt.customer_edit_rating(oid2, 尾2, 5, "店长处理得很好,改成 5 星")
        ck("差评改好评 → 工单不撤,还在待处理",
           r["ok"] and r.get("清单") == "留在清单里"
           and c.execute("SELECT status FROM task WHERE id=?", (f"TR{包2}",)).fetchone()[0] == "待处理",
           r.get("reason"))
        ck("工单上标了「顾客后来改成 5 星」",
           "改成 5 星" in (c.execute("SELECT summary FROM task WHERE id=?", (f"TR{包2}",)).fetchone()[0] or ""))
        ck("评价行上留着原来的星级(看得出改过)",
           (lambda x: x["star"] == 5 and x["star_before"] == 2 and x["edit_cnt"] == 1)(
               c.execute("SELECT * FROM rating WHERE pkg_id=?", (包2,)).fetchone()))

    # ── 超线那条线的**正向**:对的角色批了,要真的放行 ────────────────────
    #
    # ⚠️⚠️ 为什么非要单独一张单验这个:上面那几条全是「拒」,
    # 而它们**覆盖不到放行那一支**。
    # > 一个「这条线在正确的角色上放行」和一个「它对谁都拒」,
    # > **在那几条拒的判据上长得一模一样。**
    # 一条永远拒的闸会让这个功能彻底不可用,而所有拒的判据都是绿的。
    # (这正是 2026-10-14 上午那条教训:判据要验到它真能走通。)
    # 而正向那条会**真的把工单关掉**,所以不能插在上面那组里,得另起一张单。
    _上级 = (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no, name, role FROM staff WHERE role=? AND status='启用' LIMIT 1",
        (_要谁,)).fetchone())
    ck(f"库里有在职的「{_要谁}」当批准人(没有的话下面那条等于没验)", bool(_上级),
       f"一个在职的 {_要谁} 都没有 —— 那这条线上**谁都批不了**,"
       f"而上面那几条「拒」照样全绿")
    o3 = c.execute("""SELECT o.id, k.phone_tail, o.amount FROM ordr o
                        JOIN customer k ON k.id=o.customer_id
                       WHERE o.kind='定制品订单' AND o.status='已发货' AND o.shop=?
                         AND o.amount > ?
                         AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                         AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                       ORDER BY o.id LIMIT 1""", (o["shop"], _线)).fetchone()
    ck(f"有第三张单当夹具,而且订单额超过那条线({_线})", bool(o3),
       f"找不到本店一张超线、已发货、单包裹、还没到店的定制单 —— "
       f"而全库 33% 的单超线,所以这更像是夹具条件太窄")
    if o3 and _上级:
        oid3, 尾3 = o3["id"], o3["phone_tail"]
        pw.arrive({"order_id": oid3}, 顾问)
        码3 = pw.customer_issue_code(oid3, 尾3).get("试穿合身码")
        pw.verify({"order_id": oid3, "code": 码3}, 顾问)
        包3 = c.execute("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL",
                        (oid3,)).fetchone()["pkg_id"]
        rt.customer_rate(oid3, 尾3, 2, "袖子长短不一样,穿不出去")
        # ── 超线那条负向用例在**这张**单上验(它是按「订单额超线」挑出来的)──
        # 金额按性质算:**超了线,又没超这张单的订单额** ——
        # 两头都要满足,否则撞上的是「退得比收的多」那条,拒的理由就换了。
        # `min(订单额, 线+1)`:订单额 > 线 时它恒落在 (线, 订单额] 里。
        _超线额 = min(float(o3["amount"]), _线 + 1)
        ck(f"这条用例的金额真的超线(退 {_超线额:.2f} / 线 {_线} / 单额 {o3['amount']:.2f})"
           f" —— 不超线的话,下面那条拒的就不是超线",
           _超线额 > _线 and _超线额 <= float(o3["amount"]) + 0.005,
           f"退 {_超线额} vs 线 {_线} vs 单额 {o3['amount']}")
        ck(f"**超线**({_线})而批准人不是「{_要谁}」→ 拒(角色也是从库里现读的)",
           rt.close_bad_rating(
            {"pkg": 包3, "note": "已协商,顾客保留衣服,退还工费部分", "way": "部分退款",
             "approved_by": 顾问["no"], "amount": _超线额}, 店长)["code"] == "NEED_WAY")
        r3 = rt.close_bad_rating(
            {"pkg": 包3, "note": "已协商全额退款,衣服回收,顾客同意", "way": "全额退款",
             "approved_by": _上级["no"]}, 店长)
        ck(f"**超线 + 「{_要谁}」批 → 真的放行**(全额退款,金额系统现算)",
           r3.get("ok"), r3.get("reason"))
        ck("放行之后金额**落在评价那行上**,而且等于订单额(不是人填的)",
           (lambda x: x and x["handle_amount"] is not None
            and abs(x["handle_amount"] - o3["amount"]) < 0.005)(
               c.execute("SELECT * FROM rating WHERE pkg_id=?", (包3,)).fetchone()),
           f"← 订单额 {o3['amount']};落下来的是 "
           f"{(c.execute('SELECT handle_amount FROM rating WHERE pkg_id=?', (包3,)).fetchone() or ['(没有)'])[0]}"
           f" —— 金额不落库的话,「谁批了多少钱」就只在那句中文里")

    # ── 闸的要害:**判据取签收记录,不取订单状态** ─────────────────────
    # ⚠️ 第一版这一条是假绿的:它没说是哪个包裹,于是拦住它的是 `_挑包裹`
    # (「这一单 2 个包裹,没有能评的」)—— **闸压根没被碰到**,
    # 断言却写着「这一条证明闸读的是签收记录」。
    # 和咬合第三关一模一样的失效:**红了,但红的不是那一条**。
    # 所以现在**点名包裹**,并且要求错误码正好是闸给的那个。
    o3 = c.execute("""SELECT g.pkg_id, o.id oid, o.customer_id FROM ordr o
                        JOIN pkg g ON g.order_id=o.id AND g.void_at IS NULL
                       WHERE o.kind='定制品订单'
                         AND NOT EXISTS(SELECT 1 FROM pickup_item t
                                         WHERE t.pkg_id=g.pkg_id AND t.fit_result='合身')
                       LIMIT 1""").fetchone()
    ck("有一个「没签收过」的包裹当夹具", bool(o3))
    if o3:
        with closing(sqlite3.connect(T)) as cx, cx:      # 把订单状态改成「待完成」—— 模拟状态被别的路写过
            cx.execute("UPDATE ordr SET status='待完成' WHERE id=?", (o3["oid"],))
        尾3 = c.execute("SELECT phone_tail FROM customer WHERE id=?", (o3["customer_id"],)).fetchone()[0]
        r = rt.customer_rate(o3["oid"], 尾3, 5, pkg=o3["pkg_id"])
        ck("订单状态是「待完成」但这个包裹没签收记录 → **闸拒**(而且是闸拒的,不是别的条件)",
           r["code"] == "CANNOT_RATE" and "没签收" in r["reason"],
           f"{r.get('code')}:{r.get('reason')}")
        ck("这一条证明闸读的是签收记录,不是订单状态",
           c.execute("SELECT COUNT(*) FROM rating WHERE pkg_id=?", (o3["pkg_id"],)).fetchone()[0] == 0)


if __name__ == "__main__":
    main()
