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
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api, tasks

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
    A, B = adv[0], adv[1]

    print(f"\n\033[1m▸ 列表隔离 · {A['name']} 看不看得到 {B['name']} 的活\033[0m")
    print("  " + "=" * 78)
    with api.as_user(A): da = api.my_tasks()
    with api.as_user(B): db = api.my_tasks()
    with api.as_user(mgr): dm = api.my_tasks()
    ida = {t["任务号"] for t in da["任务"]}
    idb = {t["任务号"] for t in db["任务"]}
    idm = {t["任务号"] for t in dm["任务"]}
    ck(f"{A['name']} 的列表里有 {B['name']} 的任务吗", "有" if ida & idb else "没有", "没有",
       f"  ← 交叉 {len(ida & idb)} 条")
    ck(f"{A['name']} 的每一条都确实是他的",
       "是" if all(t.get("负责人") in (A["name"], None) for t in da["任务"]) else "混进别人的", "是")
    ck(f"店长看得到 {A['name']} 的", "看得到" if ida <= idm else "看不全", "看得到")
    ck(f"店长看得到 {B['name']} 的", "看得到" if idb <= idm else "看不全", "看得到")
    ck("店长的范围是全店", "全店" if "店长" in da["范围"] or "全店" in dm["范围"] else "不是", "全店")

    print(f"\n\033[1m▸ 单条隔离 · 知道单号能不能看别人的\033[0m")
    print("  " + "=" * 78)
    if not idb:
        print(f"  {R}❌{D} {B['name']} 一条任务都没有,这一节测不到"); bad += 1
    else:
        tid = sorted(idb)[0]
        with api.as_user(A): ra = api.get_task(tid)
        with api.as_user(B): rb = api.get_task(tid)
        with api.as_user(mgr): rm = api.get_task(tid)
        ck(f"{A['name']} 拿单号 {tid} 直接取", "被挡" if ra.get("error") else "取到了", "被挡",
           "  ← 列表过滤了、详情没过滤,是最常见的漏法")
        ck(f"{B['name']} 取自己的", rb.get("任务号") or "取不到", tid)
        ck("店长取本店的", rm.get("任务号") or "取不到", tid)

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
