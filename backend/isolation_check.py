# -*- coding: utf-8 -*-
"""数据隔离的咬合测试:**A 顾问不能知道 B 顾问在做什么。**

隔离这件事有个讨厌的性质:**漏了不会报错**。
少一个 WHERE,查询照样成功,只是多返回几行 —— 返回的东西看起来完全正常,
没有任何迹象说明它本不该出现。所以必须逐例对真值,而且要**从工具层测**:
从函数里测只能证明函数对,证明不了智能体拿到的那条路径也对。

这里测三种漏法,它们的表现完全不同:
  ① 列表漏      —— my_tasks 少了过滤,一次多给出一屏
  ② 单条漏      —— 列表过滤了,详情按 id 直接取(**知道单号就能看别人的**)
  ③ 写操作漏    —— 读隔离了但写没隔离(能完成别人的任务、能派给别店的人)
第 ② 种最常见:列表那边一眼能看出来,详情这边没人会去点别人的单号。
"""
import os, sys, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api, tasks
DB = tasks.DB

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0


def ck(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:46s} {str(got):14s} 应为 {want}{extra}")


def main():
    global bad
    st = {r["role"] + r["no"]: r for r in tasks.rows(
        "SELECT no,name,role,shop FROM staff WHERE status='启用'")}
    adv = [r for r in st.values() if r["role"] == "顾问" and r["shop"] == "SH001 静安旗舰店"]
    mgr = next(r for r in st.values() if r["role"] == "店长" and r["shop"] == "SH001 静安旗舰店")
    other = next(r for r in st.values() if r["role"] == "顾问" and r["shop"] != "SH001 静安旗舰店")
    if len(adv) < 2:
        print(f"{R}❌{D} 同一门店没有两个在职顾问 —— 「A 看不到 B」这条测不出来"); sys.exit(1)
    # **别钉死是哪两个人。** 上一版取 adv[0]/adv[1],重建一次数据之后
    # 挑中的那个恰好名下没有进行中的任务,「改派」整节就测不到了 ——
    # 而它不会报「测不到」,它会安静地跳过。
    # 改成**按需要的性质挑**:B 要有在办的活(改派得有东西可改),A 是另一个人。
    _live = {r["assignee_no"]: r["n"] for r in tasks.rows(
        "SELECT assignee_no,COUNT(*) n FROM schedule WHERE status='有效' "
        "AND assignee_no IS NOT NULL GROUP BY assignee_no")}
    adv = sorted(adv, key=lambda p: -_live.get(p["no"], 0))
    B, A = adv[0], adv[1]
    if not _live.get(B["no"]):
        print(f"{R}❌{D} 本店没有任何顾问有进行中的任务 —— 改派和完成都测不到"); sys.exit(1)

    print(f"\n\033[1m▸ 列表隔离 · {A['name']} 看不看得到 {B['name']} 的活\033[0m")
    print("  " + "=" * 78)
    with api.as_user(A): da = api.my_tasks()
    with api.as_user(B): db = api.my_tasks()
    with api.as_user(mgr): dm = api.my_tasks()
    ida = {t["任务号"] for t in da["任务"]}
    idb = {t["任务号"] for t in db["任务"]}
    idm = {t["任务号"] for t in dm["任务"]}

    # **交叉不是一律不许,但只许一种:被改派的那条。**
    # 改派之后原负责人仍然看得见(否则他的列表凭空少一行),于是这条
    # 同时出现在两个人的列表里 —— 这是设计,不是漏。
    # 但**只有这一种**允许:其余任何交叉都是隔离破了。
    # 加了改派之后这条不变式必须重新表述,不能笼统说「不许交叉」——
    # 笼统的判据要么冤枉功能,要么得整条删掉,而删掉就等于不再检查。
    def _reassign_pair(tid):
        r = tasks.rows("SELECT assignee_no,reassigned_from FROM schedule WHERE id=?", tid)
        if not r: return False
        pair = {r[0]["assignee_no"], r[0]["reassigned_from"]}
        return pair == {A["no"], B["no"]}

    cross = ida & idb
    bad_cross = {t for t in cross if not _reassign_pair(t)}
    ck(f"{A['name']} 和 {B['name']} 的交叉只有改派那条",
       "只有改派" if not bad_cross else f"还有 {len(bad_cross)} 条说不清的", "只有改派",
       f"  ← 交叉共 {len(cross)} 条,其中改派 {len(cross) - len(bad_cross)} 条")
    mine_or_reassigned = all(
        t.get("负责人") in (A["name"], None) or t.get("改派")
        for t in da["任务"])
    ck(f"{A['name']} 看到的每条要么是他的、要么标着改派",
       "是" if mine_or_reassigned else "混进说不清的", "是",
       "  ← 别人的活出现在他列表里而没标改派,就是漏")
    ck(f"店长看得到 {A['name']} 的", "看得到" if ida <= idm else "看不全", "看得到")
    ck(f"店长看得到 {B['name']} 的", "看得到" if idb <= idm else "看不全", "看得到")
    ck("店长的范围是全店", "全店" if "店长" in da["范围"] or "全店" in dm["范围"] else "不是", "全店")

    print(f"\n\033[1m▸ 单条隔离 · 知道单号能不能看别人的\033[0m")
    print("  " + "=" * 78)
    # 挑一条**干净属于 B** 的:不能是曾经被改派、原主是 A 的那种 ——
    # 那条 A 本来就看得见(设计如此),拿它测「A 看不到 B 的」会误报。
    clean = tasks.rows(
        "SELECT id FROM schedule WHERE assignee_no=? "
        "AND (reassigned_from IS NULL OR reassigned_from<>?) ORDER BY id",
        B["no"], A["no"])
    if not clean:
        print(f"  {R}❌{D} {B['name']} 没有一条「干净属于他」的任务,这一节测不到"); bad += 1
    else:
        tid = clean[0]["id"]
        with api.as_user(A): ra = api.get_task(tid)
        with api.as_user(B): rb = api.get_task(tid)
        with api.as_user(mgr): rm = api.get_task(tid)
        ck(f"{A['name']} 拿单号 {tid} 直接取", "被挡" if ra.get("error") else "取到了", "被挡",
           "  ← 列表过滤了、详情没过滤,是最常见的漏法")
        ck(f"{B['name']} 取自己的", rb.get("任务号") or "取不到", tid)
        ck("店长取本店的", rm.get("任务号") or "取不到", tid)

    print(f"\n\033[1m▸ 团队视图 · 店长看得到全队,顾问只看得到自己\033[0m")
    print("  " + "=" * 78)
    with api.as_user(mgr): tm = api.team_tasks()
    ck("店长的团队视图有几个人", "多于1人" if tm.get("人数", 0) > 1 else f"{tm.get('人数')}人", "多于1人")
    with api.as_user(A): ta = api.team_tasks()
    names = {g["顾问"] for g in ta.get("团队", [])}
    # 团队视图里可能出现「改派给了谁」那个人 —— 同上,那条本来就是 A 的活
    extra = names - {A["name"], "(没有负责人)"}
    ok_extra = all(any(_reassign_pair(t["任务号"])
                       for g in ta["团队"] if g["顾问"] == n for t in g.get("在办明细", []))
                   for n in extra) if extra else True
    ck(f"{A['name']} 的团队视图里只有他自己(或改派对象)",
       "只有自己" if ok_extra else f"混进 {extra}", "只有自己")
    # 找一个**和 A 没有改派关系**的第三人来试 —— 拿 B 试会撞上改派的合法交叉
    third = next((p for p in adv if p["no"] not in (A["no"], B["no"])), None)
    probe = third or B
    with api.as_user(A): r = api.team_tasks(assignee=probe["name"])
    ck(f"{A['name']} 指名查 {probe['name']}", "被挡" if r.get("error") else "查到了", "被挡")
    # **「你看不到」和「他没活」必须分开说** —— 返回空列表会被读成后者
    if r.get("error"):
        ck("  └ 而且说明了这不等于他没活", "有说" if "不等于" in r["error"] else "没说", "有说",
           "  ← 空列表会被读成「他没活」,那是隔离挡的,不是真没有")

    print(f"\n\033[1m▸ 截断要说出来\033[0m")
    print("  " + "=" * 78)
    with api.as_user(mgr): d2 = api.my_tasks()
    has = "已列出" in d2
    ck("my_tasks 会报「列了几条」", "会" if has else "不会", "会",
       "  ← 静默截断:超了 40 条无声消失,而结果本身没有任何异常")
    if has:
        ck("  └ 条数和已列出对得上",
           "一致" if d2["条数"] == d2["已列出"] or d2.get("还有没列出的") else "对不上", "一致")

    print(f"\n\033[1m▸ 写操作隔离 · 读挡住了不等于写也挡住了\033[0m")
    print("  " + "=" * 78)
    live_b = [t["任务号"] for t in db["任务"] if t.get("状态") == "有效"]
    if live_b:
        with api.as_user(A): r = api.finish_task(live_b[0], "我替他点一下")
        ck(f"{A['name']} 替 {B['name']} 点完成", "被拒" if r.get("error") or not r.get("ok") else "放行了", "被拒")
        with api.as_user(mgr): r = api.finish_task(live_b[0], "店长替他点一下")
        ck("店长替顾问点完成", "被拒" if r.get("error") or not r.get("ok") else "放行了", "被拒",
           "  ← 谁做的谁点,店长也不例外")
    else:
        print(f"  {R}❌{D} {B['name']} 没有进行中的任务,「替别人点完成」测不到"); bad += 1

    with api.as_user(A):
        r = api.assign_task("日常运维", B["name"], "顾问不该能派活", "2026-12-31 18:00")
    ck(f"{A['name']}(顾问)派任务", "被拒" if r.get("error") or not r.get("ok") else "放行了", "被拒")

    with api.as_user(mgr):
        r = api.assign_task("日常运维", other["name"], "跨店派活", "2026-12-31 18:00")
    ck(f"店长派给别店的 {other['name']}", "被拒" if r.get("error") or not r.get("ok") else "放行了", "被拒",
       f"  ← {other['name']} 在 {other['shop']}")

    print(f"\n\033[1m▸ 改派 · 原负责人不能凭空少一行\033[0m")
    print("  " + "=" * 78)
    # **要挑「当前确实是 B 的」那条。**
    # db["任务"] 现在包含被改派走的(那是设计),第二次跑这个检查时,
    # 上一次改派过去的那条还在 B 的视野里,但负责人已经是 A ——
    # 挑中它就会报「新负责人和原来是同一个人」。
    # 检查**必须能反复跑**:不幂等的检查第一次绿第二次红,
    # 而红的原因和被测的东西没关系。
    live = [r["id"] for r in tasks.rows(
        "SELECT id FROM schedule WHERE assignee_no=? AND status='有效' ORDER BY id",
        B["no"])]
    if not live:
        print(f"  {R}❌{D} {B['name']} 没有进行中的任务,改派这一节测不到"); bad += 1
    else:
        tid = live[0]
        with api.as_user(A): r = api.reassign_task(tid, A["name"], "顾问不该能改派")
        ck(f"{A['name']}(顾问)改派", "被拒" if r.get("error") else "放行了", "被拒",
           "  ← 而且要说「你没权限」,不是「找不到这个人」")
        if r.get("error"):
            ck("  └ 错误说的是权限不是找不到人",
               "说权限" if "角色" in r["error"] or "店长" in r["error"] else "说找不到人", "说权限",
               "  ← 说「找不到」会让人去核对拼写,那条路是死的")
        with api.as_user(mgr): r = api.reassign_task(tid, A["name"], "")
        ck("改派不给理由", "被拒" if not r.get("ok") else "放行了", "被拒",
           "  ← 把人的活拿走要给个说法")
        # **改完要还原。** 检查本身在改数据,不还原的话跑一次库就变一次样 ——
        # 第一次绿、第二次红,而红的原因和被测的东西没关系。
        # 一个不能反复跑的检查,实际上只在第一次有用。
        _before = tasks.rows("SELECT assignee_no,advisor,reassigned_from,reassign_reason,"
                             "reassigned_at FROM schedule WHERE id=?", tid)[0]
        try:
            with api.as_user(mgr): r = api.reassign_task(tid, A["name"], "原负责人临时有事")
            ck("店长带理由改派",
               "成了" if r.get("ok") else f"失败:{str(r.get('reason') or r.get('error'))[:20]}", "成了")
            if r.get("ok"):
                with api.as_user(B): still = [t for t in api.my_tasks()["任务"] if t["任务号"] == tid]
                ck(f"原负责人 {B['name']} 还看得见这条",
                   "看得见" if still else "看不见了", "看得见",
                   "  ← 看不见的话他的列表凭空少一行,他会以为自己记错了")
                if still:
                    ck("  └ 而且看得出是被改派走的",
                       "看得出" if still[0].get("改派") else "只显示新负责人", "看得出",
                       "  ← 只显示「负责人:林岚」比少一行还糟")
        finally:
            with sqlite3.connect(DB) as _c:
                _c.execute("UPDATE schedule SET assignee_no=?,advisor=?,reassigned_from=?,"
                           "reassign_reason=?,reassigned_at=? WHERE id=?",
                           (_before["assignee_no"], _before["advisor"], _before["reassigned_from"],
                            _before["reassign_reason"], _before["reassigned_at"], tid))

    print(f"\n\033[1m▸ 接待做完了,那条预约该跟着收尾\033[0m")
    print("  " + "=" * 78)
    # 实测:跑完 31 条旅程之后,34 条「预约到店」全是「有效」而上门全是「完结」——
    # **顾问的待办里永远躺着一条已经做完的事。**
    # 根因是两条记录之间没有真正的边,只能靠「同一个客户 + 时间接近」推。
    open_appt = tasks.rows("""SELECT COUNT(*) n FROM schedule s WHERE s.type='预约到店'
        AND s.status='有效' AND EXISTS(
          SELECT 1 FROM schedule v WHERE v.customer_id=s.customer_id
            AND v.type IN ('上门沟通','接待任务') AND v.status='完结'
            AND v.assignee_no=s.assignee_no AND v.start_ts>=s.start_ts)""")[0]["n"]
    ck("客户已接待完却还开着的预约", str(open_appt), "0",
       "  ← 每一条都是顾问待办里一件已经做完的事")
    # **推出来的关系要标出来** —— 它会在客户约了两次时认错
    import inspect as _in
    src = _in.getsource(tasks.finish_task)
    ck("  └ 自动收尾只认同一个人 + 时间在前",
       "是" if "assignee_no=?" in src and "start_ts<=?" in src else "放得太宽", "是",
       "  ← 推出来的关系和真外键长得一样,但它会在客户约了两次时认错")
    # **判据要贴着那段 SQL,不是贴着「它离某个词多远」。**
    # 上一版切 src.split("预约到店")[1][:400] 找 LIMIT 1 —— 而 SQL 里
    # 「预约到店」和 LIMIT 1 之间隔着 400 多字符,于是它报「可能一次收多条」,
    # 而代码里明明写着 LIMIT 1。**检查错了,不是代码错了。**
    _sql = src[src.find("type='预约到店'"):src.find("if cand:")]
    ck("  └ 而且一次只收最近一条",
       "是" if "LIMIT 1" in _sql and "ORDER BY start_ts DESC" in _sql else "可能一次收多条", "是",
       "  ← 宁可漏关(顾问自己会发现),不要关错(没人看得出来)")

    print(f"\n\033[1m▸ 绕道 · 别的工具能不能问出「B 在做什么」\033[0m")
    print("  " + "=" * 78)
    # 实测栽过:顾问问「周叙手上还有几件活」,模型绕开 my_tasks 去调 get_workorder
    # (那查的是**工坊师傅**),查到 0 条,答「他手头没有没做完的活」——
    # 而周叙是顾问,有 4 条任务在身,他只是不在师傅表里。
    # **空结果不等于没有,只等于这里查不到** —— 而这两者返回的都是 0 条。
    with api.as_user(A): r = api.get_workorder(artisan=B["name"])
    ck(f"拿顾问名字查工坊工单({B['name']})",
       "说清查不到" if r.get("error") else f"返回 {len(r.get('rows', r) if isinstance(r, (list, dict)) else [])} 条",
       "说清查不到", "  ← 返回 0 条会被读成「他没活」")
    if r.get("error"):
        ck("  └ 而且说明了这不等于没有", "有说" if "不等于" in r["error"] else "没说", "有说")

    print(f"\n\033[1m▸ 没有身份时 · **不许兜底成某个角色**\033[0m")
    print("  " + "=" * 78)
    d = api.my_tasks()
    ck("没登录查任务", "被挡" if d.get("error") else f"给了 {d.get('条数')} 条", "被挡")
    r = api.assign_task("日常运维", B["name"], "没登录派活", "2026-12-31 18:00")
    ck("没登录派任务", "被挡" if r.get("error") else "放行了", "被挡")
    w, a2, _ = tasks.visible_scope(None)
    ck("没身份时的查询范围", w, "1=0", "  ← 兜底成 1=1 的话,没登录反而看得到全部")

    print(f"\n\033[1m▸ 写工具都从会话取身份\033[0m")
    print("  " + "=" * 78)
    import inspect
    for name in api.WRITE_TOOLS:
        # **要 unwrap。** TOOLS 里的是脱敏包装器,直接 getsource 拿到的是那三行,
        # 检查会报「没取身份」而实际取了 —— 检查看错了对象,结论错得很像真的。
        fn = inspect.unwrap(api.TOOLS[name])
        src = inspect.getsource(fn)
        ck(f"{name} 用 whoami 取身份", "是" if "_need_me()" in src or "whoami()" in src else "没有", "是")
        # **不许有一个 role/actor 参数** —— 那就成了「我以店长身份执行」
        sig = str(inspect.signature(fn))
        ck(f"  └ 入参里没有身份字段",
           "干净" if not any(k in sig for k in ("role", "actor", "operator", "as_user")) else "有", "干净")

    print()
    if bad:
        print(f"{R}❌ 数据隔离 {bad} 处不符合预期{D}")
        print("   漏了不会报错 —— 少一个 WHERE,查询照样成功,只是多返回几行。")
        sys.exit(1)
    print(f"{G}✅ 数据隔离全部符合预期{D}")
    print("    A 顾问看不到 B 顾问的活(列表、单条、写操作三条路都试过),店长看得到全店。")


if __name__ == "__main__":
    main()
