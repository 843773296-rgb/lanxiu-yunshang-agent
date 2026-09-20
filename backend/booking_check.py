# -*- coding: utf-8 -*-
"""派单决策的咬合测试。

派单这件事有个讨厌的性质:**派错了和派对了,在库里长得一模一样** ——
都是 schedule.assignee_no 填了一个合法工号。所以不能只测「有没有报错」,
必须逐例标真值:每一种输入,应该落到哪个分支。

这里测四类派不出去的情况。它们全都可以被「随便派一个在职顾问」蒙混过去,
而蒙混过去的结果看板上是全绿的 —— 这正是要专门查的原因。
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import booking

DB = booking.DB
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「绑的顾问离职了」那一支关掉(人走了,单子还挂在他名下)',
     '绑定的顾问已离职'),
    ('抹掉一条「已到店」预约的签到时间(状态还在,依据没了)',
     '到店 / 完成的预约都有签到时间'),
    ('给一条「爽约」补上签到时间(人没来却签到了)',
     '没到店的预约不许有签到时间'),
    ('把接待任务的展示大类改成「客户预约」(两根轴被合成一根)',
     '接待任务:展示归企业、派单归客户'),
]

def check(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:44s} 判为 {got:11s} 应为 {want}{extra}")


def main():
    global bad
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    q = lambda s, *a: [dict(r) for r in c.execute(s, a)]
    print("\n\033[1m▸ 派单决策 · 逐例标真值\033[0m")
    print("  " + "=" * 76)

    # ① 绑定在职本店顾问 → 派给他
    r = q("SELECT * FROM customer WHERE advisor_no=(SELECT no FROM staff WHERE adv_code='A02') AND shop='SH001 静安旗舰店' LIMIT 1")
    if r:
        no, code, _ = booking.route(r[0])
        check("绑定在职本店顾问", code, "BOUND", f" · 派给 {no}")

    # ② 绑定的顾问已离职 → **不许派给他**
    r = q("SELECT * FROM customer WHERE advisor_no=(SELECT no FROM staff WHERE adv_code='A09') LIMIT 1")
    if not r:
        print(f"  {R}❌{D} 反例夹具丢了:没有客户挂在离职顾问名下 —— "
              f"「离职顾问的单该落池」这条从此测不出来"); globals()['bad'] = bad + 1
    else:
        no, code, _ = booking.route(r[0])
        check("绑定的顾问已离职", code, "LEFT")
        check("  └ 而且确实没派出去", "未派" if no is None else f"派给{no}", "未派")

    # ③ 没有归属顾问 → 落池
    no, code, _ = booking.route({"advisor_no": "", "shop": "SH001 静安旗舰店"})
    check("客户没有归属顾问", code, "NO_BIND")

    # ④ 档案写了个查无此人的编号 → 落池,而不是猜一个
    no, code, _ = booking.route({"advisor_no": "99999999", "shop": "SH001 静安旗舰店"})
    check("归属顾问编号查无此人", code, "BAD_BIND")

    # ⑤ 绑定的顾问不在客户所在门店 → 落池
    r = q("SELECT * FROM staff WHERE role='顾问' AND status='启用' AND shop='SH002 徐汇店' LIMIT 1")
    if r:
        no, code, _ = booking.route({"advisor_no": r[0]["no"], "shop": "SH001 静安旗舰店"})
        check("绑定顾问不在客户所在门店", code, "CROSS_SHOP")

    print("\n\033[1m▸ 一号多档 · 不许静默取第一条\033[0m")
    print("  " + "=" * 76)
    # 造数据时抓到的真 bug:book() 按手机号找客户,拿 `[0]` ——
    # 而库里有 16 个号对应多条在用档案(那正是「客户合并」要处理的场景)。
    # 后果不是报错,是**单子落到另一条档案的顾问手上** —— 跨店、错人,
    # 而客户那头看起来一切正常,直到当天有人问「谁来接待我」。
    # **「查到一条」和「查到多条只取了第一条」返回的东西长得一模一样。**
    dups = q("""SELECT phone, COUNT(*) n FROM customer WHERE archived=0
                GROUP BY phone HAVING n>1 ORDER BY phone LIMIT 1""")
    if not dups:
        print(f"  {R}❌{D} 库里没有一号多档的样本 —— 这一节测不到"); bad += 1
    else:
        ph = dups[0]["phone"]
        hits = q("SELECT id,shop,created FROM customer WHERE phone=? AND archived=0 "
                 "ORDER BY created", ph)
        before = len(q("SELECT id FROM op_log WHERE code='DUP_PHONE'"))
        import datetime
        when = (datetime.datetime.now() + datetime.timedelta(days=6)).strftime("%Y-%m-%dT14:00")
        r = booking.book(dict(phone=ph, when=when, need="检查用"))
        # **照常放行** —— 客户没做错任何事,不该因为门店档案没合并而约不上
        check("一号多档照常能约上", "能" if r.get("ok") else f"被拒:{r.get('code')}", "能")
        if r.get("ok"):
            t = q("SELECT customer_id FROM schedule WHERE id=?", r["task"])[0]
            check("  └ 派给**最早建档**的那条", t["customer_id"], hits[0]["id"],
                  f"  ← 候选 {[h['id'] for h in hits]}")
            after = len(q("SELECT id FROM op_log WHERE code='DUP_PHONE'"))
            check("  └ 而且留了痕", "记了" if after > before else "没记", "记了",
                  "  ← 不吭声的话,另一条档案上的历史永远用不上")
            # 造出来的这条清掉,**检查不许改库**
            with sqlite3.connect(DB) as _c:
                _c.execute("DELETE FROM schedule WHERE id=?", (r["task"],))
                _c.execute("DELETE FROM appointment WHERE id=?", (r["appt"],))
                _c.execute("DELETE FROM op_log WHERE code='DUP_PHONE' AND id>?", (before and
                           q("SELECT MAX(id) m FROM op_log WHERE code='DUP_PHONE'")[0]["m"] - 1 or 0,))

    print("\n\033[1m▸ 任务类型 · 两族的规则不一样\033[0m")
    print("  " + "=" * 76)
    import tasktypes as tt
    check("客户相关类型数", str(len(tt.CUSTOMER_TYPES)), "4")
    check("店铺运营类型数", str(len(tt.OPS_TYPES)), "5")
    for t in tt.CUSTOMER_TYPES:
        if tt.ref_of(t) != "customer":
            print(f"  {R}❌{D} 客户相关的「{t}」该直接挂客户号,现在挂的是 {tt.ref_of(t)}"); bad += 1
    for t in tt.OPS_TYPES:
        if tt.agent_may_propose(t):
            print(f"  {R}❌{D} agent 不该给运营任务「{t}」出建议 —— "
                  f"谁该轮培训、谁家里有事,依据不在库里"); bad += 1

    # **族 ≠ 数据规范。** 运营族里既有不挂单据的(团建/日常运维),
    # 也有必须挂单据的(订单跟踪/维保/售后)——
    # 上一版把两者合成一个 needs_customer,订单跟踪就成了无主任务。
    _ops_with_ref = [t for t in tt.OPS_TYPES if tt.ref_of(t)]
    _ops_no_ref = [t for t in tt.OPS_TYPES if not tt.ref_of(t)]
    check("运营族里有挂单据的", "有" if _ops_with_ref else "没有", "有",
          f"  ← {_ops_with_ref}")
    check("运营族里也有不挂的", "有" if _ops_no_ref else "没有", "有",
          f"  ← {_ops_no_ref}")

    # **客户号只在 ref=customer 时手填。** 订单/维保/售后的客户从单据带出 ——
    # 手填就是第二个来源,而两个来源不一致时没有任何地方会报错。
    for t in ("订单跟踪", "维保任务", "售后任务"):
        check(f"「{t}」不让手填客户号", str(tt.needs_customer(t)), "False")
        if not tt.ref_of(t):
            print(f"  {R}❌{D} 「{t}」没有指定挂哪种单据,那客户从哪儿来?"); bad += 1

    # 每种单据都要能真的解析出客户
    print()
    for kind, sql in [("customer", "SELECT id FROM customer WHERE archived=0 LIMIT 1"),
                      ("order", "SELECT id FROM ordr LIMIT 1"),
                      ("maintain", "SELECT id FROM maintain LIMIT 1"),
                      ("aftersale", "SELECT id FROM aftersale LIMIT 1")]:
        row = q(sql)
        if not row:
            print(f"  {R}❌{D} 库里一条 {kind} 都没有,「{kind} 能带出客户」这条测不到"); bad += 1
            continue
        ok2, cid, _sh, dsc = tt.resolve_ref(kind, row[0]["id"], q)
        check(f"{tt.REF_SOURCE[kind][2]}能带出客户", "带出" if (ok2 and cid) else "带不出", "带出",
              f"  ← {dsc[:38]}")
    # 查不到的单据必须明确拒绝,**不许当成「没挂单据」放过去**
    ok3, cid3, _s3, d3 = tt.resolve_ref("order", "这个单号不存在", q)
    check("查不到的单据要拒绝", "拒绝" if not ok3 else "放过", "拒绝", f"  ← {d3}")
    check("agent 只对客户相关出建议",
          str(sorted(t for t in tt.BY_NAME if tt.agent_may_propose(t))),
          str(sorted(tt.CUSTOMER_TYPES)))
    # **不许全都要传图**:全要求等于没要求,人会拍张桌子交差
    _ph = [t for t in tt.BY_NAME if tt.needs_photo(t)]
    check("要传现场照的类型不是全部", "部分" if 0 < len(_ph) < len(tt.BY_NAME) else "全部或零",
          "部分", f"  ← 现在是 {len(_ph)}/{len(tt.BY_NAME)}:{_ph}")
    check("电话回电不强制传图", str(tt.needs_photo("电话回电")), "False",
          "  ← 电话没什么可拍的,硬要求只会拍到桌面")
    # 旧类型必须都能归一,否则老单子在新界面上会落进「未知」
    for old, new in tt.LEGACY.items():
        check(f"老类型「{old}」能归一", tt.norm(old), new)

    print("\n\033[1m▸ 归属顾问 → 员工(按工号)\033[0m")
    print("  " + "=" * 76)
    # ⚠️ **这一段 2026-09-16 整体换掉了,而换的原因值得写下来。**
    #
    # 原来这里测的是「**两套编号之间的桥**」:能不能用
    # 「A01 林岚」/「A01」/「苏彧」三种写法查到人,以及**两个人同名时要放弃**。
    #
    # 而名字列删掉之后,**档案里存的就是工号,那座桥整个拆了** ——
    # 于是这几条用例开始红,**而它们红得理直气壮**:
    # 「「A01 林岚」能查到人 —— 判为查不到」。
    #
    # > **删掉一个能力,和忘了实现它,在红色里长得一模一样。**
    #
    # 正确动作是**换掉用例去测新能力**,而不是想办法让旧能力复活。
    _一 = q("SELECT no,name FROM staff WHERE role='顾问' AND status='启用' LIMIT 1")[0]
    st = booking.staff_of_advisor(_一["no"])
    check(f"按工号查得到人({_一['name']})", st["no"] if st else "查不到", _一["no"])
    st = booking.staff_of_advisor("99999999")
    check("查不到的工号不许瞎猜", "None" if st is None else st["no"], "None")
    st = booking.staff_of_advisor("")
    check("空工号不许返回人", "None" if st is None else st["no"], "None")
    # ⚠️ **同名不再是问题 —— 而这正是删掉名字列换来的。**
    # 造两个同名的人,按工号查仍然各是各的。
    dup = _一["name"]
    try:
        with sqlite3.connect(DB) as w:
            w.execute("INSERT INTO staff(no,name,role,shop,status,adv_code) "
                      "VALUES('69999999',?,'顾问','SH009 临时','启用','A99')", (dup,))
        st = booking.staff_of_advisor("69999999")
        check(f"有两个人叫「{dup}」也不影响按工号查",
              st["no"] if st else "查不到", "69999999")
        st = booking.staff_of_advisor(_一["no"])
        check("  └ 原来那个也还查得到,没被同名顶掉",
              st["no"] if st else "查不到", _一["no"])
    finally:
        with sqlite3.connect(DB) as w:
            w.execute("DELETE FROM staff WHERE no='69999999'")

    print("\n\033[1m▸ 花名册 · 一个店长带几个人\033[0m")
    print("  " + "=" * 76)
    for sh in q("SELECT DISTINCT shop FROM staff WHERE shop<>'' ORDER BY shop"):
        mg = q("SELECT name FROM staff WHERE shop=? AND role='店长'", sh["shop"])
        ad = q("SELECT name FROM staff WHERE shop=? AND role='顾问' AND status='启用'", sh["shop"])
        lf = q("SELECT name FROM staff WHERE shop=? AND role='顾问' AND status<>'启用'", sh["shop"])
        print(f"  ·  {sh['shop']:18s} 店长 {mg[0]['name'] if mg else '(缺)':5s} "
              f"顾问 {len(ad)} 人{('(另有离职 %d 人)' % len(lf)) if lf else ''}")

    # 跨店绑定:客户在这个店,归属顾问却在另一个店
    print("\n\033[1m▸ 客户绑定 · 不许跨店\033[0m")
    print("  " + "=" * 76)
    # ⚠️ 这里原来是 `ON s.adv_code = substr(c.advisor,1,3)` ——
    # **靠截字符串前三位来连人**。名字列 2026-09-16 删了,现在是正经的引用。
    # ⚠️ **排除 `FX-` 开头的测试夹具。**
    # 2026-09-20 加了三个夹具客户(无主 / 坏工号 / 跨店),
    # 为的是让 `ownership.py` 里那三条分支**有东西可测** ——
    # **一条永远不触发的分支,和一条正确的分支,在通过率上长得一模一样。**
    #
    # 这里排除的只是 `FX-` 前缀那几条,**真实客户的跨店绑定照样会红** ——
    # 这一条要守的是「演示数据里不该有跨店」,而夹具是故意的,不是数据错。
    # (夹具由 tools/backfill_fixtures.py 造,依赖它的检查在自己的 `前提` 里声明了。)
    cross = q("""SELECT COUNT(*) n FROM customer c LEFT JOIN staff s
                 ON s.no = c.advisor_no
                 WHERE c.advisor_no IS NOT NULL AND c.advisor_no<>''
                   AND c.id NOT LIKE 'FX-%'
                   AND (s.shop IS NULL OR s.shop<>c.shop)""")[0]["n"]
    check("跨店绑定的客户数", str(cross), "0",
          "  ← 跨店绑定会让预约永远派不出去,却看不出是数据的错")

    # ⑦bis 展示大类 和 派单族 是两根轴,不许合成一根
    import tasktypes as _tt
    check("九个子类型都归进了展示大类",
          str(sum(1 for t in _tt.BY_NAME if _tt.属于大类(t))), str(len(_tt.BY_NAME)),
          "  ← 漏一个,界面上那一条会掉进「未分组」,而未分组会被当成新的一类")
    # 接待任务:展示上是「企业任务」,派单上是「客户族」。**这一处正是两根轴的分界** ——
    # 合成一根的话它会掉进「只能店长派」,而客户上门了才有接待,它本来能按归属自动派。
    check("接待任务:展示归企业、派单归客户",
          f"{_tt.属于大类('接待任务')}/{_tt.family('接待任务')}", "企业任务/客户",
          "  ← 两根轴只差这一处,差的这一处就是分界线本身")
    check("大类名和旧类型名重名的那三个还在",
          str(sum(1 for k in _tt.大类 if k in _tt.LEGACY)), "3",
          "  ← 「订单任务」既是旧的单级类型名、又是装三个子类型的大类名;"
          "norm() 会把它折成一个叶子,当成大类传进来就会悄悄丢掉另外两个")

    # ⑧ 签到时间 ⇔ 到店 —— 状态和它的依据必须对得上
    #
    # 「已到店」是门店 Pad 上点了签到才变过去的,签到时间就是这个状态的**依据**。
    # 缺了它,预约详情页的时间轴上「到店签到」那一行直接消失,而页面不会报错 ——
    # **一条没有签到时间的「已到店」,和一条正常的,在列表页上长得一模一样。**
    # 实测过:建预约的代码有两处,带押金的那处写了签到时间,不带押金的那处传 None,
    # 于是库里 7 条到店 / 完成的预约一条签到时间都没有,字段在、路径从来没被走过。
    到 = q("SELECT COUNT(*) n FROM appointment WHERE status IN ('已到店','已完成')")[0]["n"]
    缺 = q("SELECT COUNT(*) n FROM appointment WHERE status IN ('已到店','已完成') "
           "AND (checkin_ts IS NULL OR checkin_ts='')")[0]["n"]
    check("样本量:到店 / 完成的预约", "够" if 到 >= 5 else f"只有 {到} 条", "够",
          "  ← 空集合上这条性质自动成立,**那不叫通过,叫没扫到东西**")
    check("到店 / 完成的预约都有签到时间", f"{到 - 缺}/{到}", f"{到}/{到}")
    多 = q("SELECT COUNT(*) n FROM appointment WHERE status NOT IN ('已到店','已完成') "
           "AND checkin_ts IS NOT NULL")[0]["n"]
    check("没到店的预约不许有签到时间", str(多), "0",
          "  ← 「爽约」还带着签到时间的话,爽约率就是假的")
    晚 = q("SELECT COUNT(*) n FROM appointment WHERE checkin_ts IS NOT NULL "
           "AND checkin_ts > datetime(start_ts, '+2 hours')")[0]["n"]
    check("签到时间落在预约时段附近", str(晚), "0",
          "  ← 签到晚于预约两小时以上,多半是日期整体挪动时漏挪了这一列")

    print()
    if bad:
        print(f"{R}❌ 派单决策 {bad} 处不符合预期{D}"); sys.exit(1)
    print(f"{G}✅ 派单决策全部符合预期{D}")
    print("    派错和派对在库里长得一模一样 —— 所以每一例都得标真值,不能只看有没有报错。")


if __name__ == "__main__":
    main()
