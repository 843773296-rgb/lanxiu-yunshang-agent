"""小程序浏览情况 · 两个只读查询(用户 2026-11-28 拍「造数据 + 给助手加查询」)

  · browse_history(customer, days=30)   这个客户最近在小程序看了什么、停多久、加购 / 分享没有、后来买没买
  · browse_funnel(days=30, spu=None, sort="浏览人数", limit=10)
                                        按商品的浏览漏斗:看的人 → 加购 → 分享 → 下单(找「看得多买得少」)

⚠️ **还没挂到助手上**:挂工具要改工具说明区和规矩表,那两处归另一个会话维护,用户拍「等它回来」。
   文件名故意不叫 api_browse:`backend/api_*.py` 按约定要登记进门面 api.py 的「子模块们」,而 api.py 那时还不该碰;
   挂工具那天再决定要不要改名并登记(11-28 门禁 api 拆分约定挡下)。
现在只有检查(backend/browse_check.py)在真调这两个函数。

口径(怎么数)在 `knowledge/browse.漏斗`,这里只取数、按身份收范围。
范围和会员 / 服务记录同一套(api_member._单客范围 / _名单范围):顾问看自己名下、店长看本店、总部运营看全部。
**造数参数是拟的**(见 knowledge/browse.py 顶上),返回里带一句「口径说明」,免得把拟定的转化率读成真实的。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import datetime as _dt
import os
import sqlite3
import sys

import api
import worldclock as _wc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
import browse as _K   # noqa: E402

表 = "mp_event"
口径说明 = "小程序浏览是虚拟数据,停留 / 加购 / 分享的造数参数是拟定的(knowledge/browse.py),不是这家店的实测转化率"
排序们 = ("浏览人数", "转化率低", "加购率", "分享率")
看得多买得少_最少人数 = 20      # 按「转化率低」排时,浏览人数不到这个数的不进榜 —— 3 个人看、0 个人买不叫「买得少」


def _连():
    con = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _有表(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (表,)).fetchone())


def _窗口(days):
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None, None, dict(error=f"days 要是天数(整数),收到的是「{days}」")
    if days < 1 or days > 730:
        return None, None, dict(error="days 只收 1–730 天 —— 浏览数据最多铺了两年")
    今 = _wc.今天()
    起 = (今 - _dt.timedelta(days=days - 1)).isoformat()
    止 = (今 + _dt.timedelta(days=1)).isoformat()      # 含今天
    return 起, 止, None


def browse_history(customer=None, days=30):
    """**一个客户**最近在小程序看了什么 —— 按商品汇总:看了几次、一共停多久、最长一次多久、加购 / 分享没有、
    这段时间里在这件上下单没有。顾问打电话前看一眼「她最近在看什么」。"""
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer:
        return dict(error="要给一个客户号或姓名 —— 这个工具看的是**一个人**的浏览")
    起, 止, 错 = _窗口(days)
    if 错:
        return 错
    import api_member as _m
    con = _连()
    try:
        cs = [dict(con.execute("SELECT id,name,shop,advisor_no FROM customer WHERE id=?", (x["id"],)).fetchone())
              for x in api._认客户(customer)[0]]
        if not cs:
            return dict(error=f"没有这个客户「{customer}」—— **这是数据问题,不是他没看过**")
        if len(cs) > 1:
            return {"error": f"「{customer}」命中 {len(cs)} 个客户,要改用客户号",
                    "候选": [{"客户号": c["id"], "门店": c["shop"]} for c in cs[:5]]}
        c0 = cs[0]
        拒 = _m._单客范围(me, c0)
        if 拒:
            return 拒
        if not _有表(con):
            return dict(error="库里还没有小程序浏览数据(mp_event 表不在)—— **是没铺数据,不是他没看过**")
        行 = [dict(r) for r in con.execute(
            f"SELECT session_id, ts, event, entry, spu, dwell_s, order_id FROM {表} "
            "WHERE customer_id=? AND ts>=? AND ts<? ORDER BY ts, id", (c0["id"], 起, 止))]
        看过 = sorted({x["spu"] for x in 行 if x["spu"]})
        名 = {r["spu"]: r["name"] for r in con.execute(
            f"SELECT spu, name FROM product WHERE spu IN ({','.join('?' * len(看过))})", 看过)} if 看过 else {}
    finally:
        con.close()
    if not 行:
        return {"客户": c0["id"], "看的范围": f"近 {days} 天", "进来几次": 0,
                "说明": "这段时间没在小程序里看过商品", "口径说明": 口径说明}
    品 = {}
    for r in 行:
        s = r["spu"]
        if not s:
            continue
        d = 品.setdefault(s, {"商品": s, "商品名": 名.get(s, ""), "看了几次": 0, "一共停留秒": 0, "最长一次秒": 0,
                              "加购了": False, "分享了": False, "下单了": False, "最近一次": None})
        if r["event"] == _K.进入详情:
            d["看了几次"] += 1; d["最近一次"] = r["ts"]
        elif r["event"] == _K.离开详情 and r["dwell_s"] is not None:
            d["一共停留秒"] += r["dwell_s"]; d["最长一次秒"] = max(d["最长一次秒"], r["dwell_s"])
        elif r["event"] == _K.加购:
            d["加购了"] = True
        elif r["event"] == _K.分享:
            d["分享了"] = True
        elif r["event"] == _K.下单:
            d["下单了"] = True
    清单 = sorted(品.values(), key=lambda x: (-x["一共停留秒"], x["商品"]))
    return {"客户": c0["id"], "看的范围": f"近 {days} 天(到世界今天 {_wc.今天()})",
            "进来几次": len({r["session_id"] for r in 行}), "最近一次进来": 行[-1]["ts"],
            "看过的商品": 清单[:20], "还有几件没列": max(0, len(清单) - 20),
            "口径说明": 口径说明}


def browse_funnel(days=30, spu=None, sort="浏览人数", limit=10):
    """按商品的浏览漏斗:浏览人数 → 加购人数 → 分享人数 → 下单人数(都按人),外加停留中位秒。
    sort:浏览人数(默认)/ 转化率低(看得多买得少,浏览人数 ≥ 20 才进榜)/ 加购率 / 分享率。
    范围跟身份走:顾问只数自己名下的客户、店长本店、总部运营全公司。"""
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if sort not in 排序们:
        return dict(error=f"sort 只收 {' / '.join(排序们)},收到的是「{sort}」")
    try:
        limit = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        return dict(error=f"limit 要是整数,收到的是「{limit}」")
    起, 止, 错 = _窗口(days)
    if 错:
        return 错
    import api_member as _m
    片, 参, 说 = _m._名单范围(me)
    con = _连()
    try:
        if not _有表(con):
            return dict(error="库里还没有小程序浏览数据(mp_event 表不在)—— **是没铺数据,不是没人看**")
        条 = ["e.ts>=?", "e.ts<?"]; args = [起, 止]
        if spu:
            条.append("e.spu=?"); args.append(spu)
        if 片:
            条.append(f"e.customer_id IN (SELECT id FROM customer WHERE {片})"); args += 参
        行 = [dict(r) for r in con.execute(
            f"SELECT e.customer_id, e.event, e.spu, e.dwell_s, e.order_id FROM {表} e WHERE " + " AND ".join(条), args)]
        漏 = _K.漏斗(行)
        名 = {r["spu"]: r["name"] for r in con.execute("SELECT spu, name FROM product")} if 漏 else {}
    finally:
        con.close()
    if not 漏:
        return {"看的范围": f"近 {days} 天 · {说}", "商品数": 0,
                "说明": "这段时间、这个范围里没有人在小程序看过" + (f"「{spu}」" if spu else "商品") + " —— **是没有浏览,不是率为 0**",
                "口径说明": 口径说明}
    行们 = [{"商品": s, "商品名": 名.get(s, ""), **v} for s, v in 漏.items()]
    门槛说明 = None
    if sort == "浏览人数":
        行们.sort(key=lambda x: (-x["浏览人数"], x["商品"]))
    elif sort == "转化率低":
        够 = [x for x in 行们 if x["浏览人数"] >= 看得多买得少_最少人数]
        门槛说明 = f"浏览人数不到 {看得多买得少_最少人数} 的 {len(行们) - len(够)} 件没进榜(人太少,率不说明问题)"
        行们 = sorted(够, key=lambda x: (x["转化率"], -x["浏览人数"], x["商品"]))
    else:
        行们.sort(key=lambda x: (-x[sort], -x["浏览人数"], x["商品"]))
    out = {"看的范围": f"近 {days} 天(到世界今天 {_wc.今天()})· {说}", "排序": sort,
           "商品数": len(漏), "列出": 行们[:limit],
           "口径": "人数都按人数(一个人加购三次算一个);停留取中位数;转化率 = 下单人数 ÷ 浏览人数",
           "口径说明": 口径说明}
    if 门槛说明:
        out["门槛"] = 门槛说明
    return out
