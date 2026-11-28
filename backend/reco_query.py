"""推荐 · 三个只读查询(用户 2026-11-28 拍:协同过滤 + 矩阵分解都做;相似人群 行为 7 画像 3;给人推荐两个都给)

  · similar_customers(customer, k=50)  跟 A 像的人(行为 + 画像),以及能把 A 买过的哪几件推给谁
  · recommend_for(customer)             给这位客户推什么:协同过滤 10 件 + 矩阵分解 10 件,各标来源;都推不出退到热销(标「兜底」)
  · also_viewed(spu)                    看了这件的人还看了(商品对商品,归一化)

口径在 knowledge/reco.py / knowledge/lookalike.py(**参数大多是拍脑袋的,数据是造的**,见那两个文件顶上)。
这里只取数、按身份收范围、加两道闸:
  · 不同意营销 / 注销中 / 已注销 / 没账户的不推 —— 和购买喜好推荐(A-266)同一句判断
  · 90 天冷却:**直接调 opportunity_store._上次推送 + oppo_obj.冷却中**(用户拍「和已有的共用这一道闸」)——
    那道闸是**按人**的:这个人 90 天内被任何一种回捞推过就整个跳过,比「同一件不重复」更严

⚠️ 还没挂到助手上(同 browse_query):挂工具要改 api.py 描述区和规矩表,等维护方回来。
⚠️ 文件名不叫 api_*:那样要登进 api.py 的「子模块们」。

算一次模型约 10 秒(纯 Python 矩阵分解占大头),按「库路径 + 浏览行数 / 最大号 + 订单行数 + 世界今天」缓存在进程里 ——
数据一变(每日平移、重铺浏览、新订单)键就变,下一次重算。
"""
import datetime as _dt
import os
import sqlite3
import sys
from contextlib import closing

import api
import worldclock as _wc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
import browse as _B      # noqa: E402
import lookalike as _L   # noqa: E402
import reco as _R        # noqa: E402

口径说明 = ("推荐基于虚拟的小程序浏览和订单,参数大多是拟定的(knowledge/reco.py、knowledge/lookalike.py);"
        "只能说明算法怎么推,不能读成真实的成功率")
_缓存 = {}


def _连():
    con = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _键(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mp_event'").fetchone():
        return None
    a = c.execute("SELECT COUNT(*), MAX(id) FROM mp_event").fetchone()
    b = c.execute("SELECT COUNT(*) FROM ordr_item").fetchone()[0]
    t = c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()
    return (api.DB, a[0], a[1], b, t[0] if t else None)


def _模型(要分解=True):
    with closing(_连()) as c:
        k = _键(c)
        if k is None:
            return None
        m = _缓存.get(k)
        if m and (m.get("U") is not None or not 要分解):
            return m
        if not m:
            今 = _wc.今天()
            浏览 = [dict(r) for r in c.execute("SELECT customer_id, ts, event, spu, dwell_s FROM mp_event")]
            订单 = [dict(r) for r in c.execute(
                "SELECT o.customer_id, o.created, i.spu, o.amount FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
                "WHERE o.customer_id IS NOT NULL AND i.spu IS NOT NULL AND o.status NOT IN ('已取消','待付款')")]
            客 = [dict(r) for r in c.execute("SELECT * FROM customer WHERE merged_into IS NULL")]
            孩子们 = {str(r[0]) for r in c.execute(
                "SELECT DISTINCT customer_id FROM wearer WHERE relation IN (%s)" % ",".join("?" * len(_L.孩子关系)),
                sorted(_L.孩子关系))}
            品 = {r["spu"]: dict(r) for r in c.execute("SELECT spu, name, category, status FROM product")}
            买过, 花, 销量 = {}, {}, {}
            for r in 订单:
                u = str(r["customer_id"])
                买过.setdefault(u, set()).add(r["spu"])
                花[u] = 花.get(u, 0.0) + float(r["amount"] or 0)
                销量[r["spu"]] = 销量.get(r["spu"], 0) + 1
            排 = sorted(花, key=lambda u: (花[u], u))
            消费档之 = {u: min(4, i * 5 // max(1, len(排))) for i, u in enumerate(排)}
            M = _L.行为向量(浏览, 订单, 今)
            W, 模 = _L.逆人数加权(M)
            m = {"今": 今, "M": M, "W": W, "模": 模, "买过": 买过, "销量": 销量, "品": 品,
                 "画像": {str(x["id"]): _L.画像(x, 孩子们, 消费档之, 今) for x in 客},
                 "相": _R.商品相似(_R.交互(浏览, 今)),
                 "可推": {s for s, p in 品.items() if p["status"] == "上架"}, "U": None, "V": None}
            _缓存.clear()
            _缓存[k] = m
        if 要分解 and m["U"] is None:
            m["U"], m["V"] = _R.矩阵分解(m["M"])
        return m


def _认一个(customer, me):
    import api_member as _m
    with closing(_连()) as con:
        cs = [dict(con.execute("SELECT id,name,shop,advisor_no FROM customer WHERE id=?", (x["id"],)).fetchone())
              for x in api._认客户(customer)[0]]
    if not cs:
        return None, dict(error=f"没有这个客户「{customer}」")
    if len(cs) > 1:
        return None, {"error": f"「{customer}」命中 {len(cs)} 个客户,要改用客户号",
                      "候选": [{"客户号": c["id"], "门店": c["shop"]} for c in cs[:5]]}
    拒 = _m._单客范围(me, cs[0])
    return (None, 拒) if 拒 else (cs[0], None)


def _名(m, s):
    return (m["品"].get(s) or {}).get("name", "")


def 能推吗(c, cust, 今, 查冷却=True):
    """→ None(能推)或不能推的原因。营销同意那句和 opportunity_store.购买偏好回捞 同一句;冷却直接调它的函数。
    查冷却=False:召回名单用(顾问本来就在打这通召回电话,冷却管的是「系统主动推」,不管顾问在电话里提一句商品)。"""
    import opportunity_store as _os
    import oppo_obj as _K
    能 = c.execute("SELECT a.status, a.marketing_consent FROM customer cu JOIN account a ON a.id=cu.account_id "
                   "WHERE cu.id=?", (cust,)).fetchone()
    if not 能 or 能[0] in ("注销中", "已注销") or not 能[1]:
        return "不同意营销 / 注销 / 没有账户"
    if not 查冷却:
        return None
    上次 = _os._上次推送(c, cust)
    if _K.冷却中(_dt.date.fromisoformat(str(上次)[:10]) if 上次 else None, 今):
        return f"90 天内推过(上次 {str(上次)[:10]})"
    return None


def similar_customers(customer=None, k=50):
    """跟 A 像的人 + 能把 A 买过的哪几件推给谁。像的人只在**问的人看得到的范围里**找(顾问名下 / 店长本店 / 总部全部)。"""
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer:
        return dict(error="要给一个客户号或姓名 —— 这是「找跟这位客户像的人」")
    try:
        k = max(1, min(100, int(k)))
    except (TypeError, ValueError):
        return dict(error=f"k 要是整数,收到的是「{k}」")
    A, 错 = _认一个(customer, me)
    if 错:
        return 错
    m = _模型(要分解=False)
    if m is None:
        return dict(error="库里还没有小程序浏览数据 —— 是没铺数据,不是没人像她")
    a = str(A["id"])
    import api_member as _m
    片, 参, 说 = _m._名单范围(me)
    with closing(_连()) as c:
        范围内 = sorted(str(r[0]) for r in c.execute(
            "SELECT id FROM customer WHERE merged_into IS NULL" + (f" AND {片}" if 片 else ""), 参))
        像 = _L.找像的人(a, 范围内, m["W"], m["模"], m["画像"], 比重=_L.行为比重, k=k)
        推 = _L.推A买过的(m["买过"].get(a, set()), 像, m["买过"], m["可推"], A的分=m["M"].get(a))
        今 = m["今"]
        挡 = {}
        能 = []
        for x in 推:
            why = 能推吗(c, x["客户"], 今)
            if why:
                挡[why.split("(")[0]] = 挡.get(why.split("(")[0], 0) + 1
            else:
                能.append({**x, "推的商品": [{"商品": s, "商品名": _名(m, s)} for s in x["推"]]})
    return {"A": a, "A 买过几件": len(m["买过"].get(a, ())), "找的范围": 说,
            "像的人": len(像), "其中能推": len(能), "没推的原因": 挡,
            "比重": f"行为 {_L.行为比重:.0%} · 画像 {1 - _L.行为比重:.0%}(用户 11-28 拍)",
            "能推的": [{k2: v for k2, v in x.items() if k2 != "推"} for x in 能[:20]],
            "还有几位没列": max(0, len(能) - 20), "口径说明": 口径说明}


def recommend_for(customer=None):
    """给这位客户推什么:协同过滤 10 件(带「因为她看过 X」)+ 矩阵分解 10 件;她买过的、不在售的不推。
    两个都推不出 → 她买过的品类里的热销,标「兜底」。"""
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer:
        return dict(error="要给一个客户号或姓名")
    A, 错 = _认一个(customer, me)
    if 错:
        return 错
    m = _模型(要分解=True)
    if m is None:
        return dict(error="库里还没有小程序浏览数据 —— 是没铺数据")
    a = str(A["id"])
    她 = m["M"].get(a, {})
    买 = m["买过"].get(a, set())
    协 = _R.给人推荐_协同(她, m["相"], m["可推"], 买, 销量=m["销量"])
    分 = _R.给人推荐_分解(m["U"].get(a), m["V"], m["可推"], 买)
    out = {"客户": a, "口径说明": 口径说明,
           "协同过滤": [{**x, "商品名": _名(m, x["商品"]), "因为看过的商品名": _名(m, x["因为看过"])} for x in 协],
           "矩阵分解": [{**x, "商品名": _名(m, x["商品"])} for x in 分]}
    if not 协 and not 分:
        out["兜底"] = [{"商品": s, "商品名": _名(m, s)} for s in _R.热销兜底(
            {s: p["category"] for s, p in m["品"].items()}, m["销量"], m["可推"], 买,
            {m["品"][s]["category"] for s in 买 if s in m["品"]})]
        out["说明"] = "她没有可用的浏览 / 购买记录,两个算法都推不出 —— 下面是她买过的品类里的热销(没买过就是全店热销),是兜底不是推荐"
    return out


def also_viewed(spu=None, k=10):
    """看了这件的人还看了(只列在售的;两件至少 5 个人一起看过才算相关)。"""
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not spu:
        return dict(error="要给一个商品编号")
    m = _模型(要分解=False)
    if m is None:
        return dict(error="库里还没有小程序浏览数据 —— 是没铺数据")
    if spu not in m["品"]:
        return dict(error=f"没有这件商品「{spu}」")
    xs = _R.看了还看(m["相"], spu, m["可推"], k)
    if not xs:
        return {"商品": spu, "商品名": _名(m, spu), "说明": f"没有一件和它至少 {_R.最少共同人数} 个人一起看过 —— 是数据不够,不是没人看",
                "口径说明": 口径说明}
    return {"商品": spu, "商品名": _名(m, spu),
            "看了还看": [{"商品": s, "商品名": _名(m, s), "相似度": round(v, 4), "一起看过的人数": n} for s, v, n in xs],
            "口径说明": 口径说明}
