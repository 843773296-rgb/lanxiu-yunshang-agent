#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评价**看的那一头**的检查 —— 盯住 `api.rating_overview` 答不答得出店长真正要问的。

`backend/rating_check.py` 查的是**库里的数据**对不对。这份查的是**工具返回的东西**
对不对 —— 两件不同的事,而且第二件原来**一条判据都没有**:

    2026-09-28 之前 rating_overview 只返回一个整体平均。
    而 `knowledge/rating.这个星级能说明什么()` 的「能说」第二条明写着
    「不同门店 / 不同时间段的交付体验互相比」——
    **口径承诺了两个切分,工具一个都不给,而这不会让任何东西变红。**

⚠️ **这类不一致的特征是「两边各自合法」**:4.4 这个数完全合法,口径那句话也完全合法,
只有把两个放在一起看才是矛盾。所以它必须被**一条跨两边的判据**抓住 ——
判据本身就得同时读口径和读工具。

## 里面最关键的一条:趋势不许拿窗口两头相减

真跑第一次就撞上了:窗口 120 天从 05-31 起,`2026-05` **只进来一天**(7 条),
拿它当趋势起点,总部口径算出 **-0.08 下降**,而同期静安是 **+0.17 上升** ——
**趋势的符号被一个噪声点决定。**

所以这份检查**自己挑窗口**:让窗口起点落在某个月的 15 号,于是「前端残月」
必然存在。⚠️ 这一步不是为了方便 —— 如果窗口起点恰好是 1 号,这条判据就**空跑**了,
而空跑和通过在输出上一模一样(2026-09-28 交接里刚写过:被关掉的守卫比没有更糟,
**空跑的守卫比被关掉的还糟,因为清单上它还是绿的**)。
"""
import datetime as _dt
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]
import api
import rating as R
import worldclock

MGR = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
ADV = {"no": "60000003", "name": "周叙", "role": "顾问", "shop": "SH001 静安旗舰店"}
HQ = {"no": "60000009", "name": "魏欣新", "role": "总部运营", "shop": ""}
FAIL, N = [], [0]


def ck(名, 取, 说=""):
    """⚠️ **延迟求值**(和 knowledge/rating.py 同一个理由):判据崩了的时候,
    如果 ok 是先算出来再传进来的,整个自测会当场死掉 —— 那条 ❌ 连打印的机会都没有,
    而「崩了」和「判错了」下一步完全不同。"""
    N[0] += 1
    try:
        ok = bool(取())
    except Exception as e:
        ok, 说 = False, f"{说}  ← **崩了**:{type(e).__name__}: {e}"
    print(f"  {'✅' if ok else '❌'} {名}{('  ' + str(说)[:170]) if 说 else ''}")
    if not ok: FAIL.append(名)


def 挑一个必然有残月的窗口():
    """返回 (days, 残月, 当月)。

    让窗口起点落在**三个月前的 15 号** —— 于是那个月一定是被窗口切开的残月,
    而当月一定还没走完。两头各一个「不完整的月」,中间至少两个完整月。
    """
    今 = worldclock.今天()
    y, m = 今.year, 今.month - 3
    while m <= 0:
        y, m = y - 1, m + 12
    起 = _dt.date(y, m, 15)
    return (今 - 起).days, f"{y}-{m:02d}", 今.strftime("%Y-%m")


def main():
    print("评价概况(看的那一头)· 检查")
    print("=" * 92)
    days, 残月, 当月 = 挑一个必然有残月的窗口()
    print(f"  ℹ 世界今天 {worldclock.今天()};窗口挑成 days={days},"
          f"于是起点落在 {残月}-15 —— **残月必然存在,判据不会空跑**")

    with api.as_user(HQ):
        hq = api.rating_overview(days)
    with api.as_user(MGR):
        mg = api.rating_overview(days)
    with api.as_user(ADV):
        adv = api.rating_overview(days)

    # ── 一、谁看得到(业务 2026-09-27:只给店长看,不进顾问考核)──────────
    ck("顾问看不到评价概况(业务 2026-09-27:不进顾问考核)",
       lambda: adv.get("条数") == 0 and "按门店" not in adv, f"顾问拿到:{sorted(adv)}")
    ck("店长只看得到本店(跨店比较要总部身份)",
       lambda: isinstance(mg["按门店"], str) and "跨店" in mg["按门店"], mg["按门店"])
    ck("总部看得到多家店,而且每家都带条数",
       lambda: (isinstance(hq["按门店"], dict) and len(hq["按门店"]) >= 2
                and all("条数" in v for v in hq["按门店"].values())),
       f"{len(hq['按门店']) if isinstance(hq['按门店'], dict) else '—'} 家")
    ck("店长看到的条数比总部少(本店 ⊂ 全店)",
       lambda: 0 < mg["条数"] < hq["条数"], f"店长 {mg['条数']} / 总部 {hq['条数']}")

    # ── 二、口径承诺的两个切分,工具都得给 ──────────────────────────────
    # **判据同时读口径和读工具** —— 抄一份「应该有门店和月份」进来的话,
    # 哪天口径改了,这里不会知道。
    能说, _ = R.这个星级能说明什么()
    承诺了比门店 = any("门店" in x for x in 能说)
    承诺了比时段 = any(("时间段" in x or "时段" in x) for x in 能说)
    ck("口径说「能比门店」→ 工具真给了按门店(总部身份下)",
       lambda: (not 承诺了比门店) or isinstance(hq["按门店"], dict),
       f"口径承诺={承诺了比门店}")
    ck("口径说「能比时间段」→ 工具真给了按月",
       lambda: (not 承诺了比时段) or isinstance(hq["按月"], dict),
       f"口径承诺={承诺了比时段}")

    # ── 三、⚠️ 趋势不许被残月带反 ────────────────────────────────────
    趋 = hq.get("趋势_只看完整月", "")
    没算 = hq.get("没算进趋势的月份", {})
    ck(f"被窗口切开的那个残月({残月})**没有**被当成趋势的起点",
       lambda: not str(趋).startswith(残月), f"趋势={趋}")
    ck(f"残月({残月})被单独列出来,而且说清了为什么不算",
       lambda: 残月 in 没算 and "起点" in 没算[残月], f"没算进趋势的:{sorted(没算)}")
    ck(f"当月({当月})也不当趋势的终点,但**照样报出来**(店长要看的就是它)",
       lambda: (当月 not in str(趋).split("→")[-1] if "→" in str(趋) else True)
               and 当月 in 没算 and "没走完" in 没算[当月], f"没算进趋势的:{sorted(没算)}")
    ck("趋势那一行报了两端各自的条数(**没有条数的平均不能当结论**)",
       lambda: str(趋).count("条") >= 2, 趋)
    ck("趋势只用完整月之后,两端都是满月(条数不该只有个把条)",
       lambda: all(v["条数"] >= 30 for k, v in hq["按月"].items()
                   if k not in 没算), f"完整月:{[k for k in hq['按月'] if k not in 没算]}")

    # ── 四、算不出来的时候给话,不给数 ────────────────────────────────
    with api.as_user(HQ):
        # ⚠️ 原来是 `rating_overview(3)`,注释写「3 天:不可能跨两个自然月」——
        # **每个月 1 号、2 号这句话是假的**(10-01 往回 3 天是 09-29~10-01)。2026-10-01 当天 CI 就红了。
        # 改成「本月 1 号到今天」那么多天:**结构上**落不出这个月,不靠今天恰好是几号。
        import worldclock as _wc
        窄 = api.rating_overview(_wc.今天().day - 1)     # 起点 = 本月 1 号(1 号当天就是 0 天:只看今天)
    ck("窗口只落在一个月里时,「按月」给的是一句话而不是一个假趋势",
       lambda: (窄.get("条数") == 0
                or (isinstance(窄.get("按月"), str) and "看不出趋势" in 窄["按月"])),
       f"条数 {窄.get('条数')} / 按月 {str(窄.get('按月'))[:60]}")
    ck("每个分组的平均旁边都有条数(按月那一份)",
       lambda: all("条数" in v for v in hq["按月"].values()), f"{len(hq['按月'])} 个月")
    ck("返回里带着「不能说明什么」(和口径同一份,没抄)",
       lambda: hq["这个数不能说明什么"] == R.这个星级能说明什么()[1], "")

    print("=" * 92)
    if FAIL:
        print(f"\033[31m❌ 评价概况 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 评价概况 {N[0]} 条全过(窗口 days={days},残月 {残月},当月 {当月})\033[0m")


咬合 = [
    ("把「前端残月剔掉」那个条件改成恒真", "被窗口切开的那个残月"),
    ("把「当月不参与趋势」那个条件改成恒真", "当月"),
    ("把 rating_overview 的店长身份闸去掉", "顾问看不到评价概况"),
    ("让「按月」在只有一个月时也返回字典(假趋势)", "窗口只落在一个月里时"),
]

if __name__ == "__main__":
    main()
