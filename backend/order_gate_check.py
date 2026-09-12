# -*- coding: utf-8 -*-
"""下单前置条件的检查 —— **定制订单的量体不许超期,判不了要说判不了。**

规则出处:`12-成长与生命周期.md` 第五节
「超期的量体记录**不是「参考值」,是「无效值」** —— 下单前必须拦下」。

## 这条检查的三档,和别的检查不一样

大部分检查只有「过 / 挂」两档。这一条有三档,因为**「判不了」是个独立的状态**:

    可以      前置齐了
    不可以    明确缺什么(没量体 / 超期)—— **这是违规,要红**
    判不了    不知道给谁做的 —— **这不是违规,是数据不全,单独报**

把「判不了」并进「可以」,等于默认放行;并进「不可以」,
等于把 19 单数据不全的单子说成违规。**两种都在撒谎,只是方向不同。**

## 上一版量错了,教训值得留着

第一版按**客户**取「最近一条量体」,而一个客户名下可以有本人和两个孩子 ——
取到的多半是**大人自己的**新记录,把孩子那条停在 342 天前的盖住了。
于是量出「75/76 全部有效」,而真相是这条规则**根本没在孩子身上跑过**。

**一个客户多个着装人时,「最近一条」和「这一单那个人的最近一条」
返回的东西长得一模一样。**
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import knowledge.growth as G
import knowledge.order_gate as OG

DB = os.path.join(HERE, "lanxiu.db")
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def judge(c, o):
    """一单的结论。**按行判** —— 一单可以给不止一个人做。

    实测 7 单是「两件童款加一件女款」,一家三口订同款。
    只看订单级的 `wearer_id` 表达不了这种单:只能挑一个人填,而挑谁都不对。

    整单的结论是各行里**最坏的那个**:
    任何一行定不了或超期,整单就不能下 —— 那一行照样要裁剪。
    """
    rows = c.execute("""SELECT i.id, i.wearer_id, p.gender g, p.kind
                        FROM ordr_item i JOIN product p ON p.spu=i.spu
                        WHERE i.order_id=?""", (o["id"],)).fetchall()
    定制行 = [r for r in rows if r["kind"] == "定制品"]
    if 定制行:
        worst = None
        for r in 定制行:
            k, why = _judge_row(c, o, r)
            if k == "不可以": return (k, why)       # 最坏的,直接返回
            if k == "判不了": worst = (k, why)
        return worst or ("可以", f"{len(定制行)} 行定制,着装人都定得下来且量体有效")
    # 没有定制行(纯标品,或者压根没有明细)—— 退回订单级的老判法
    if not OG.需要量体吗(o["kind"]):
        return OG.能不能下单(o["kind"], None, None, None)
    wid = o["wearer_id"]
    if not wid:
        return OG.能不能下单(o["kind"], None, None, None)
    w = c.execute("SELECT id,name,gender,birthday FROM wearer WHERE id=?", (wid,)).fetchone()
    if not w:
        return ("判不了", f"订单上的着装人 {wid} 在 wearer 表里找不到")
    m = c.execute("SELECT measured_at FROM measure_rec WHERE wearer_id=? AND measured_at<=? "
                  "ORDER BY measured_at DESC LIMIT 1", (wid, o["created"])).fetchone()
    if not m:
        return OG.能不能下单(o["kind"], w["name"], None, None)
    exp = None
    if w["birthday"] and w["gender"]:
        try:
            exp = G.measure_expired(w["gender"], w["birthday"],
                                    m["measured_at"][:10], o["created"][:10])
        except Exception:
            exp = None
    return OG.能不能下单(o["kind"], w["name"], m["measured_at"], exp)


def _judge_row(c, o, r):
    """一行的结论。"""
    if not r["wearer_id"]:
        return ("判不了", f"这一行({r['g']}款)定不到人 —— "
                          f"通用款分不出性别,或者名下有不止一个人对得上。"
                          f"**判不了不等于可以**")
    w = c.execute("SELECT id,name,gender,birthday FROM wearer WHERE id=?",
                  (r["wearer_id"],)).fetchone()
    if not w:
        return ("判不了", f"行上的着装人 {r['wearer_id']} 在 wearer 表里找不到")
    m = c.execute("SELECT measured_at FROM measure_rec WHERE wearer_id=? AND measured_at<=? "
                  "ORDER BY measured_at DESC LIMIT 1",
                  (w["id"], o["created"])).fetchone()
    if not m:
        return OG.能不能下单("定制品订单", w["name"], None, None)
    exp = None
    if w["birthday"] and w["gender"]:
        try:
            exp = G.measure_expired(w["gender"], w["birthday"],
                                    m["measured_at"][:10], o["created"][:10])
        except Exception:
            exp = None
    return OG.能不能下单("定制品订单", w["name"], m["measured_at"], exp)


def main():
    print("下单前置条件 · 检查")
    print("=" * 80)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = list(c.execute("SELECT id,customer_id,kind,created,wearer_id FROM ordr"))
    res = [(o, judge(c, o)) for o in rows]
    可以 = [x for x in res if x[1][0] == "可以"]
    不可以 = [x for x in res if x[1][0] == "不可以"]
    判不了 = [x for x in res if x[1][0] == "判不了"]

    # ① 三档必须加起来等于总数 —— **少一档就是有单子被静默丢掉了**。
    ck("三档加起来等于订单总数", len(可以) + len(不可以) + len(判不了) == len(rows),
       len(rows), f"可以 {len(可以)} / 不可以 {len(不可以)} / 判不了 {len(判不了)}")

    # ② **规则必须在未成年身上跑过。** 成人复量周期 365 天,几乎拦不住东西;
    #    这条规则真正咬合的地方在孩子身上(180 天、120 天)。
    #    在成人上全绿而没碰过孩子,等于这条规则**从没被真正执行过**。
    今天 = datetime.date(2026, 9, 12)
    未成年单 = c.execute("""SELECT COUNT(*) FROM ordr_item i JOIN wearer w ON w.id=i.wearer_id
                          WHERE w.birthday IS NOT NULL
                            AND julianday(?) - julianday(w.birthday) < 18*365.25""",
                       (今天.isoformat(),)).fetchone()[0]
    ck("规则在未成年着装人身上跑过(按行数)", 未成年单 > 0, 未成年单,
       "成人 365 天几乎拦不住东西 —— 在成人上全绿等于这条规则没被真正执行过")

    # ③ 「不可以」的每一条,理由里必须说清缺什么。
    糊 = [o["id"] for o, (k, why) in 不可以 if "量体" not in why and "超期" not in why]
    ck("每条「不可以」都说清缺什么", not 糊, len(不可以) or 1,
       f"说不清的 {糊[:3]}" if 糊 else "")

    # ④ 「判不了」不许混进「可以」。**按行判** ——
    #    判据从「订单级 wearer_id 为空」改成「有定制行落不到人」,
    #    因为着装人现在挂在行上:一单可以给不止一个人做。
    混 = []
    for o, (k, why) in 可以:
        空行 = c.execute("""SELECT COUNT(*) FROM ordr_item i JOIN product p ON p.spu=i.spu
                          WHERE i.order_id=? AND p.kind='定制品'
                            AND i.wearer_id IS NULL""", (o["id"],)).fetchone()[0]
        if 空行: 混.append(o["id"])
    ck("「判不了」没有被当成「可以」", not 混, len(可以),
       "把判不了并进可以,等于默认放行" if not 混 else f"混了 {混[:3]}")

    # ⑤ 标品不受这条管 —— **默认严,但不许拦错人**。
    标品挂 = [o["id"] for o, (k, _) in res
              if o["kind"] in OG.无需量体的订单类型 and k != "可以"]
    n5 = len([o for o in rows if o["kind"] in OG.无需量体的订单类型])
    ck("标品订单不受量体规则管", not 标品挂, n5,
       "现货成衣按尺码卖,拦它是拦错人")

    # ⑥ **口径逐例标真值,专挑边界。** 前五条验的全是「机制」——
    #    三档加总、理由说得清、标品不受管 —— 这些在一个
    #    **把所有单都判成「可以」的实现上照样全部成立**。
    #    咬合实测:把「超期不算违规」改掉,违规从 3 掉到 1,**五条全绿**。
    #    绝对判定就该逐例标真值,而且专挑边界(正好等于周期天数那一天)。
    cases = [
        ("超期一天", {"过期": True, "已过天数": 181, "允许天数": 180, "原因": "3–12 岁"}, "不可以"),
        ("正好到期", {"过期": False, "已过天数": 180, "允许天数": 180, "原因": "3–12 岁"}, "可以"),
        ("还差一天", {"过期": False, "已过天数": 179, "允许天数": 180, "原因": "3–12 岁"}, "可以"),
        ("孕期立即复量", {"过期": True, "已过天数": 1, "允许天数": 0, "原因": "孕期"}, "不可以"),
    ]
    bad6 = [n for n, exp, want in cases
            if OG.能不能下单("定制品订单", "某人", "2026-01-01", exp)[0] != want]
    # 没量体 / 判不了 这两档也钉上
    if OG.能不能下单("定制品订单", "某人", None, None)[0] != "不可以": bad6.append("没量体")
    if OG.能不能下单("定制品订单", None, None, None)[0] != "判不了": bad6.append("不知给谁做")
    if OG.能不能下单("标品订单", None, None, None)[0] != "可以": bad6.append("标品")
    ck("口径逐例(含边界:正好到期那天算可用)", not bad6, len(cases) + 3,
       ("挂了:" + "、".join(bad6)) if bad6 else "")

    # ⑦ **库里的锚点:那个反例夹具必须还在违规名单里。**
    #
    # 锚点钉的是 `fix_order_measure.夹具着装人` —— 一个**故意留着不修**的
    # 超期订单(刘星野,11 岁,量体过期 272 天)。
    # 为什么要故意留:`seed.py` 反例夹具那段写着
    # 「**没有用例的规则可以是错的,而且永远不会被发现** —— 反例在种子数据里是资产」。
    # 全修干净的话,这条规则一个用例都没有,而检查照样全绿。
    #
    # 这条抓的是取数取错人:按**客户**取「最近一条量体」会拿到大人的新记录,
    # 把孩子那条停在 272 天前的盖住 —— 我第一次量就是这么错的,
    # **量出「75/76 全部有效」,而规则根本没在孩子身上跑过。**
    sys.path.insert(0, HERE)
    import fix_order_measure as FX
    实际违规 = {o["wearer_id"] for o, (k, _) in 不可以 if o["wearer_id"]}
    漏 = set(FX.夹具着装人集) - 实际违规
    ck("反例夹具一个都不许少(规则得有用例)", not 漏, len(FX.夹具着装人集),
       f"漏了 {漏} —— {FX.夹具说明}" if 漏 else FX.夹具说明[:40])

    # ⑦·2 **除了夹具,不该再有别的超期单。**
    #     和上一条是一对:上一条防「规则失去用例」,这一条防「数据又脏回去」。
    #     只有上一条的话,新造出来的违规会混在里面没人发现。
    多出来 = 实际违规 - set(FX.夹具着装人集)
    ck("除了夹具没有别的超期单", not 多出来, len(实际违规),
       f"多出来 {多出来} —— 跑 `python3 tools/migrate_order_measure.py --go`"
       if 多出来 else "")

    # ⑧ **每个填上的着装人,必须是「唯一可能」的那个。**
    #
    # 前面几条验的还是机制。咬合实测:把回填从「唯一量过体的」放宽成
    # 「随便挑第一个量过体的」,判不了从 8 掉到 4,**而检查全绿** ——
    # 多填的那 4 单每一条都长得很正常,没有任何地方会报错。
    #
    # ⚠️ 期望值**从数据独立算**,不调 `assign_wearers` ——
    # 调它就是同源谬误:实现放宽了,期望跟着放宽,检查什么都看不见。
    # 独立的判据是两句话:名下只有这一个人,或者下单前只有这一个人量过体。
    # 判据换成**商品性别**:童款 → 名下唯一的未成年人;男/女款 → 名下唯一的同性成人。
    # 原来的判据是「名下唯一 / 唯一量过体」,而实测 560005 买的是**童装**、
    # 名下只有一个成人,于是被填给了 32 岁的大人 ——
    # **规则跑得欢,查的是错的人。**
    #
    # ⚠️ 期望值**从库里独立算**,不调 `assign_item_wearers` ——
    # 调它就是同源谬误:实现放宽了,期望跟着放宽,检查什么都看不见。
    import datetime as _dt2
    今 = "2026-09-12"
    def _成年2(b):
        return bool(b) and (_dt2.date.fromisoformat(今)
                            - _dt2.date.fromisoformat(b)).days / 365.25 >= 18
    n8 = bad8 = 0; 例8 = []
    for r in c.execute("""SELECT i.id, i.wearer_id, i.order_id, p.gender g, o.customer_id
                          FROM ordr_item i JOIN product p ON p.spu=i.spu
                          JOIN ordr o ON o.id=i.order_id
                          WHERE p.kind='定制品' AND i.wearer_id IS NOT NULL"""):
        n8 += 1
        ws = [tuple(x) for x in c.execute(
            "SELECT id,name,gender,birthday FROM wearer WHERE customer_id=? "
            "AND status='在用'", (r["customer_id"],))]
        w, _ = OG.定位着装人(r["g"], ws, _成年2)
        if w and w[0] == r["wearer_id"]:
            continue
        bad8 += 1
        if len(例8) < 3:
            例8.append((r["order_id"][-6:], r["g"] + "款", r["wearer_id"],
                        "商品性别定出来的是 " + (w[1] if w else "定不了")))
    ck("每行的着装人都是商品性别定出来的那个", bad8 == 0, n8,
       f"对不上的 {例8}" if bad8 else "童款→唯一的孩子;男/女款→唯一的同性成人")

    print("-" * 80)
    print(f"  可以 {len(可以)} · **不可以 {len(不可以)}** · 判不了 {len(判不了)}")
    for o, (k, why) in 不可以[:5]:
        print(f"    ❌ {o['id'][-6:]} {o['customer_id']} {why[:76]}")
    if 判不了:
        print(f"  判不了的 {len(判不了)} 单是**数据不全,不是违规** —— "
              f"订单上没着装人,而客户名下不止一个人。"
              f"跑 `tools/migrate_order_wearer.py` 看明细")
    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 下单前置条件 9 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
