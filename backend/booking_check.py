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
    r = q("SELECT * FROM customer WHERE advisor='A02 周叙' AND shop='SH001 静安旗舰店' LIMIT 1")
    if r:
        no, code, _ = booking.route(r[0])
        check("绑定在职本店顾问", code, "BOUND", f" · 派给 {no}")

    # ② 绑定的顾问已离职 → **不许派给他**
    r = q("SELECT * FROM customer WHERE advisor LIKE 'A09%' LIMIT 1")
    if not r:
        print(f"  {R}❌{D} 反例夹具丢了:没有客户挂在离职顾问名下 —— "
              f"「离职顾问的单该落池」这条从此测不出来"); globals()['bad'] = bad + 1
    else:
        no, code, _ = booking.route(r[0])
        check("绑定的顾问已离职", code, "LEFT")
        check("  └ 而且确实没派出去", "未派" if no is None else f"派给{no}", "未派")

    # ③ 没有归属顾问 → 落池
    no, code, _ = booking.route({"advisor": "", "shop": "SH001 静安旗舰店"})
    check("客户没有归属顾问", code, "NO_BIND")

    # ④ 档案写了个查无此人的编号 → 落池,而不是猜一个
    no, code, _ = booking.route({"advisor": "A99 张三", "shop": "SH001 静安旗舰店"})
    check("归属顾问编号查无此人", code, "BAD_BIND")

    # ⑤ 绑定的顾问不在客户所在门店 → 落池
    r = q("SELECT * FROM staff WHERE role='顾问' AND status='启用' AND shop='SH002 徐汇店' LIMIT 1")
    if r:
        no, code, _ = booking.route({"advisor": r[0]["adv_code"], "shop": "SH001 静安旗舰店"})
        check("绑定顾问不在客户所在门店", code, "CROSS_SHOP")

    print("\n\033[1m▸ 任务类型 · 两族的规则不一样\033[0m")
    print("  " + "=" * 76)
    import tasktypes as tt
    check("客户相关类型数", str(len(tt.CUSTOMER_TYPES)), "4")
    check("店铺运营类型数", str(len(tt.OPS_TYPES)), "5")
    for t in tt.CUSTOMER_TYPES:
        if not tt.info(t)["needs_customer"]:
            print(f"  {R}❌{D} 客户相关的「{t}」竟然不要求挂客户"); bad += 1
    for t in tt.OPS_TYPES:
        if tt.info(t)["needs_customer"]:
            print(f"  {R}❌{D} 店铺运营的「{t}」竟然要求挂客户"); bad += 1
        if tt.agent_may_propose(t):
            print(f"  {R}❌{D} agent 不该给运营任务「{t}」出建议 —— "
                  f"谁该轮培训、谁家里有事,依据不在库里"); bad += 1
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

    print("\n\033[1m▸ 两套编号之间的桥\033[0m")
    print("  " + "=" * 76)
    for who, want in [("A01 林岚", "60000002"), ("A05", "60000011"), ("苏彧", "60000011")]:
        st = booking.staff_of_advisor(who)
        check(f"「{who}」能查到人", st["no"] if st else "查不到", want)
    st = booking.staff_of_advisor("A99 查无此人")
    check("查不到的编号不许瞎猜", "None" if st is None else st["no"], "None")

    # 同名的两个人 —— 桥必须放弃,不能返回其中一个。
    # **这条得自己造现场**:花名册里正好没有同名的人,不造就永远测不到,
    # 而没红过的检查等于没有。造完必删,失败也删。
    dup = q("SELECT name FROM staff WHERE role='顾问' AND status='启用' LIMIT 1")[0]["name"]
    try:
        with sqlite3.connect(DB) as w:
            w.execute("INSERT INTO staff(no,name,role,shop,status,adv_code) "
                      "VALUES('69999999',?,'顾问','SH009 临时','启用','A99')", (dup,))
        st = booking.staff_of_advisor(dup)          # 按姓名查 —— 现在有两个人叫这个名字
        check(f"有两个人叫「{dup}」时按姓名查要放弃",
              "None" if st is None else st["no"], "None")
        st = booking.staff_of_advisor("A99")        # 但按 A 号查仍然唯一,该查得到
        check("  └ 同名不影响按编号查", st["no"] if st else "查不到", "69999999")
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
    cross = q("""SELECT COUNT(*) n FROM customer c LEFT JOIN staff s
                 ON s.adv_code = substr(c.advisor,1,3)
                 WHERE c.advisor<>'' AND (s.shop IS NULL OR s.shop<>c.shop)""")[0]["n"]
    check("跨店绑定的客户数", str(cross), "0",
          "  ← 跨店绑定会让预约永远派不出去,却看不出是数据的错")

    print()
    if bad:
        print(f"{R}❌ 派单决策 {bad} 处不符合预期{D}"); sys.exit(1)
    print(f"{G}✅ 派单决策全部符合预期{D}")
    print("    派错和派对在库里长得一模一样 —— 所以每一例都得标真值,不能只看有没有报错。")


if __name__ == "__main__":
    main()
