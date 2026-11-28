#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小程序浏览行为造数 —— 一个动作一行,和已有订单对得上(用户 2026-11-28 拍)

    python3 tools/backfill_browse.py              # 铺(先清掉自己造的,可反复跑)
    python3 tools/backfill_browse.py --selftest   # 合成小库上自证:对得上订单 / 时间先后 / 确定性

参数全在 `knowledge/browse.py`(**拟定的,不是实测**)。这里只管按参数铺。

## 表:mp_event(一个动作一行)

    session_id  一次进小程序(从进列表到离开)的编号 MS0000001 …
    customer_id 谁
    ts          什么时候(到秒;每日平移按「整列日期」自动跟着挪)
    event       进入列表 / 进入详情 / 离开详情 / 加购 / 分享 / 下单 / 收藏(名字在口径模块里定一次;收藏 11-28 补)
    entry       这一次从哪进来的(首页推荐 / 分类列表 / 搜索结果 / 活动专题 / 好友分享)
    spu         看的哪件(进入列表那一行为空)
    dwell_s     只在「离开详情」那一行:这次在详情页停了几秒
    order_id    只在「下单」那一行:对应的订单号

## 怎么对得上订单

  · **小程序下的单**:下单那一刻之前有一次「下单那次浏览」(进详情 → 多半加购 → 下单,
    下单那一行的 ts 就是订单的 created),再往前 1–14 天有 0–3 次回来看
  · **别的渠道下的单**:35% 的人下单前 1–30 天在小程序看过那件(只看,不在小程序下单)
  · **其余全是「看了没买」**:每人两年里平均进来几次,看的多半是自己买过的品类,
    商品按卖得多少加权(卖得多的被看得多 —— 但不按销量定死,有噪声)
  · 「看了没买」只铺到**世界今天零点之前**(不落到世界的未来,也不随机器时刻变 —— 重建两次一样)

## 随机流

自己的 `random.Random(种子)`,不抽全局那条(见 backend/seed_rng_check.py:插一行就整体挪位)。
遍历一律按主键排序 —— 同一份库、同一份代码,铺出来逐行一样。
"""
import datetime as dt, math, os, random, sqlite3, sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import browse as K
import worldclock
from dbpath import 路径 as _库路径
DB = _库路径()
种子 = 20261128
表 = "mp_event"

# ⚠️ 表名在 DDL 里写字面量,不用 {表} 拼 —— tools/table_origin_check 从**文本**上认「这张表是谁建的」
DDL = """
CREATE TABLE IF NOT EXISTS mp_event(
  -- 小程序浏览行为,一个动作一行(用户 2026-11-28 拍;造数参数是拟的,见 knowledge/browse.py)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event TEXT NOT NULL,
  entry TEXT,
  spu TEXT,
  dwell_s INTEGER,
  order_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_mp_event_cust_ts ON mp_event(customer_id, ts);
-- 不建按商品的索引:按商品出漏斗是整表聚合,27 万行扫一遍零点几秒;那个索引要多占约 10MB,
-- 而库每次检查都要拷一份(11-28 实测:表 23MB / 按客户索引 11MB / 按商品索引 10MB)
"""

小程序渠道 = "微信小程序"
_F = "%Y-%m-%d %H:%M:%S"


def 建表(c):
    c.executescript(DDL)


def _解析(s):
    s = str(s)
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:len(dt.datetime(2000, 1, 1).strftime(f))], f)
        except ValueError:
            continue
    return None


def _泊松(rng, lam):
    # Knuth;lam 只有个位数,够用
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _停留(rng, kind, 有意向):
    中 = K.停留中位秒.get(kind, K.停留中位秒["标品"]) * (K.有意向倍数 if 有意向 else 1)
    v = int(round(rng.lognormvariate(math.log(中), K.停留_sigma)))
    return max(K.停留下限秒, min(K.停留上限秒, v))


def _挑时刻(rng, 日):
    h = rng.choices(range(24), weights=K.时段权重)[0]
    return dt.datetime.combine(日, dt.time(h, rng.randrange(60), rng.randrange(60)))


class _铺:
    def __init__(self, rng):
        self.rng, self.行, self.n会话 = rng, [], 0

    def 新会话(self):
        self.n会话 += 1
        return f"MS{self.n会话:07d}"

    def 记(self, sid, cid, t, ev, entry, spu=None, dwell=None, oid=None):
        self.行.append((sid, cid, t.strftime(_F), ev, entry, spu, dwell, oid))

    def 看一件(self, sid, cid, t, entry, spu, kind, 有意向, 加购p=None):
        """进详情 → (加购)(分享) → 离开详情。返回离开的时刻。"""
        rng = self.rng
        d = _停留(rng, kind, 有意向)
        self.记(sid, cid, t, K.进入详情, entry, spu)
        p加 = 加购p if 加购p is not None else (K.加购率_有意向 if 有意向 else K.加购率.get(kind, K.加购率["标品"]))
        p分 = K.分享率_有意向 if 有意向 else K.分享率
        if rng.random() < p加:
            self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.3, 0.9)))), K.加购, entry, spu)
        if rng.random() < p分:
            self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.2, 0.95)))), K.分享, entry, spu)
        p藏 = K.收藏率_有意向 if 有意向 else K.收藏率.get(kind, K.收藏率["标品"])
        if rng.random() < p藏:
            self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.2, 0.95)))), K.收藏, entry, spu)
        离 = t + dt.timedelta(seconds=d)
        self.记(sid, cid, 离, K.离开详情, entry, spu, dwell=d)
        return 离

    def 一次(self, cid, 起, spus, 品, 有意向):
        """一次进小程序,依次看 spus。返回这次最后离开的时刻。"""
        rng = self.rng
        sid = self.新会话()
        entry = rng.choices(list(K.入口权重), weights=list(K.入口权重.values()))[0]
        t = 起
        if entry not in K.直达详情的入口:
            self.记(sid, cid, t, K.进入列表, entry)
            t += dt.timedelta(seconds=rng.randint(3, 40))
        for i, s in enumerate(spus):
            if i:
                t += dt.timedelta(seconds=rng.randint(2, 20))
            t = self.看一件(sid, cid, t, entry, s, 品[s]["kind"], 有意向)
        return t

    def 下单那次(self, cid, 下单于, oid, spus, 品):
        """下单那一刻之前的那次浏览:倒着排,最后一行「下单」的 ts = 订单 created。"""
        rng = self.rng
        sid = self.新会话()
        entry = rng.choices(list(K.入口权重), weights=list(K.入口权重.values()))[0]
        # 先算好每件停多久,再从下单时刻往回推起点
        停 = [_停留(rng, 品[s]["kind"], True) for s in spus]
        间隔 = [rng.randint(2, 20) for _ in spus]
        结算 = rng.randint(20, 120)
        总 = sum(停) + sum(间隔) + 结算 + (0 if entry in K.直达详情的入口 else rng.randint(3, 40))
        t = 下单于 - dt.timedelta(seconds=总)
        if entry not in K.直达详情的入口:
            self.记(sid, cid, t, K.进入列表, entry)
            t += dt.timedelta(seconds=rng.randint(3, 40))
        for s, d, g in zip(spus, 停, 间隔):
            kind = 品[s]["kind"]
            self.记(sid, cid, t, K.进入详情, entry, s)
            if rng.random() < K.下单那次加购率.get(kind, K.下单那次加购率["标品"]):
                self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.4, 0.95)))), K.加购, entry, s)
            if rng.random() < K.分享率_有意向:
                self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.2, 0.95)))), K.分享, entry, s)
            if rng.random() < K.下单那次收藏率:
                self.记(sid, cid, t + dt.timedelta(seconds=max(1, int(d * rng.uniform(0.2, 0.95)))), K.收藏, entry, s)
            t += dt.timedelta(seconds=d)
            self.记(sid, cid, t, K.离开详情, entry, s, dwell=d)
            t += dt.timedelta(seconds=g)
        for s in spus:
            self.记(sid, cid, 下单于, K.下单, entry, s, oid=oid)


def 造数的输入(c):
    品 = {r[0]: {"kind": r[1], "category": r[2], "status": r[3],
                "上架": (_解析(r[4]) or _解析(r[5]) or dt.datetime(2000, 1, 1)).date()}
         for r in c.execute("SELECT spu, kind, category, status, on_shelf_at, created FROM product ORDER BY spu")}
    单 = {}
    for oid, cid, src, cr, spu in c.execute(
            "SELECT o.id, o.customer_id, o.source, o.created, i.spu FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
            "WHERE o.customer_id IS NOT NULL AND i.spu IS NOT NULL ORDER BY o.id, i.id"):
        if spu not in 品 or not _解析(cr):
            continue
        d = 单.setdefault(oid, {"cid": str(cid), "src": src, "created": _解析(cr), "spus": []})
        if spu not in d["spus"]:
            d["spus"].append(spu)
    客 = [(str(r[0]), (_解析(r[1]) or dt.datetime(2024, 1, 1)).date())
         for r in c.execute("SELECT id, created FROM customer WHERE merged_into IS NULL ORDER BY id")]
    return 品, 单, 客


def 铺数(品, 单, 客, 今, rng):
    """纯函数(不碰库):输入 → 行列表。今 = 世界今天(date);「看了没买」只铺到今天零点之前。"""
    p = _铺(rng)
    卖 = {}
    买过品类 = {}
    小程序买过 = set()
    for oid in sorted(单):
        d = 单[oid]
        for s in d["spus"]:
            卖[s] = 卖.get(s, 0) + 1
            买过品类.setdefault(d["cid"], set()).add(品[s]["category"])
        if d["src"] == 小程序渠道:
            小程序买过.add(d["cid"])

    # ① 和订单对得上的那几次
    for oid in sorted(单):
        d = 单[oid]
        cid, T, spus = d["cid"], d["created"], d["spus"]
        if d["src"] == 小程序渠道:
            p.下单那次(cid, T, oid, spus, 品)
            n = 0
            while n < K.下单前回看_最多 and rng.random() < K.下单前回看_继续概率:
                n += 1
                日 = (T - dt.timedelta(days=rng.randint(1, K.下单前回看_最早天))).date()
                同类 = [s for s in 品 if 品[s]["category"] == 品[spus[0]]["category"] and s not in spus
                        and 品[s]["status"] == "上架" and 品[s]["上架"] <= 日]
                看 = list(spus) + rng.sample(同类, min(len(同类), rng.randint(0, 2)))
                rng.shuffle(看)
                p.一次(cid, _挑时刻(rng, 日), 看, 品, True)
        elif rng.random() < K.别渠道先看过的比例:
            日 = (T - dt.timedelta(days=rng.randint(1, K.别渠道先看_最早天))).date()
            p.一次(cid, _挑时刻(rng, 日), list(spus), 品, True)

    # ② 看了没买(只铺到世界今天零点之前)
    上架的 = sorted((s for s in 品 if 品[s]["status"] == "上架"), key=lambda s: (品[s]["上架"], s))
    权 = {s: (卖.get(s, 0) + 3) ** 0.7 for s in 上架的}
    末日 = 今 - dt.timedelta(days=1)
    for cid, 起日 in 客:
        if 起日 > 末日:
            continue
        lam = K.人均次数_小程序买过 if cid in 小程序买过 else K.人均次数_其余
        跨 = (末日 - 起日).days
        次 = _泊松(rng, lam)
        # 11-28 用户补「给所有顾客都模拟上」:至少成功一次。只管「抽到 0 次」不够 ——
        # 建档早的人抽到 1–2 次、偏偏都落在商品上架之前,照样一行没有(第一版这样漏了 26 人)
        要保底 = K.每人至少进来一次
        成, 试 = 0, 0
        while 成 < max(次, 1 if 要保底 else 0) and 试 < 次 + (20 if 要保底 else 0):
            试 += 1
            日 = 起日 + dt.timedelta(days=rng.randint(0, 跨))
            池 = [s for s in 上架的 if 品[s]["上架"] <= 日]
            if not 池:
                continue                 # 那天一件在售的都没有(建档早、商品上架晚)—— 保底的那次换个日子再抽
            老 = 买过品类.get(cid)
            if 老 and rng.random() < K.看老品类的概率:
                池2 = [s for s in 池 if 品[s]["category"] in 老]
                池 = 池2 or 池
            k = 1
            while k < K.一次最多看 and rng.random() < K.再看一件的概率:
                k += 1
            看 = []
            for _ in range(k):
                s = rng.choices(池, weights=[权[x] for x in 池])[0]
                if s not in 看:
                    看.append(s)
            起 = _挑时刻(rng, 日)
            末 = p.一次(cid, 起, 看, 品, False)
            if 末.date() > 末日:          # 晚上 23 点多进来、看到了第二天 —— 整次不要(不落到世界的未来)
                p.行 = [r for r in p.行 if r[0] != f"MS{p.n会话:07d}"]
                continue
            成 += 1
    p.行.sort(key=lambda r: (r[2], r[0]))
    return p.行


def 铺(db=None, 说=print):
    db = db or DB          # 运行时现取 —— 默认参数在 def 那一刻就绑死,`模块.DB = 副本` 会改不动(11-03 丢过数据)
    今 = worldclock.今天()
    with closing(sqlite3.connect(db)) as c:
        建表(c)
        品, 单, 客 = 造数的输入(c)
        if not 品 or not 单 or not 客:
            说(f"  ❌ 输入取空了(商品 {len(品)} / 订单 {len(单)} / 客户 {len(客)})—— **这是没扫到东西,不是铺好了**")
            return 1
        行 = 铺数(品, 单, 客, 今, random.Random(种子))
        with c:
            n旧 = c.execute(f"SELECT COUNT(*) FROM {表}").fetchone()[0]
            c.execute(f"DELETE FROM {表}")
            c.execute("DELETE FROM sqlite_sequence WHERE name=?", (表,))
            c.executemany(f"INSERT INTO {表}(session_id,customer_id,ts,event,entry,spu,dwell_s,order_id) "
                          "VALUES (?,?,?,?,?,?,?,?)", 行)
        会话 = len({r[0] for r in 行})
        说(f"  ✅ {表}:{len(行)} 行 / {会话} 次进小程序(原有 {n旧} 行已清);"
           f"订单 {len(单)} 笔(小程序 {sum(1 for d in 单.values() if d['src'] == 小程序渠道)})· 客户 {len(客)} · 世界今天 {今}")
    return 0


# ── 咬合记录(规格在 tools/bite_specs.json)────────────────────────────────
咬合 = [
    ("小程序订单不铺「下单那次浏览」", "的「下单」行有 "),
    ("保底只管「抽到 0 次」(建档早、抽到的日子都在上架前的人照样一行没有)", "保底:"),
]


# ── 自测:合成小库(不碰真库)────────────────────────────────────────────
def _自测():
    import collections
    bad = []
    今 = dt.date(2026, 6, 30)
    品 = {f"P{i}": {"kind": "定制品" if i % 3 == 0 else "标品", "category": f"C{i % 4}", "status": "上架",
                   "上架": dt.date(2025, 1, 1)} for i in range(20)}
    品["P99"] = {"kind": "标品", "category": "C0", "status": "待上架", "上架": dt.date(2026, 7, 1)}
    单 = {}
    for i in range(300):
        单[f"O{i:04d}"] = {"cid": f"C{i % 60}", "src": 小程序渠道 if i % 2 else "门店 Pad",
                          "created": dt.datetime(2026, 1, 1, 10) + dt.timedelta(hours=13 * i), "spus": [f"P{i % 20}"]}
    客 = [(f"C{i}", dt.date(2025, 6, 1)) for i in range(80)]
    # 建档早(2023)、商品 2025 才上架的一批:随机抽的日子多半一件在售的都没有 —— 保底要换日子再抽(11-28 第一版漏过 26 人)
    客 += [(f"E{i}", dt.date(2023, 1, 1)) for i in range(40)]
    行 = 铺数(品, 单, 客, 今, random.Random(种子))
    if 行 != 铺数(品, 单, 客, 今, random.Random(种子)):
        bad.append("同一份输入铺两次结果不同 —— 不确定")
    if not 行:
        return ["一行都没铺出来"]
    会 = collections.defaultdict(list)
    for r in 行:
        会[r[0]].append(r)
    # 每笔小程序订单:有一行「下单」,ts = created;同一次会话里先进过那件的详情
    for oid, d in 单.items():
        下 = [r for r in 行 if r[3] == K.下单 and r[7] == oid]
        if d["src"] == 小程序渠道:
            if len(下) != len(d["spus"]):
                bad.append(f"小程序订单 {oid} 的「下单」行有 {len(下)} 条,应 {len(d['spus'])}"); continue
            if 下[0][2] != d["created"].strftime(_F):
                bad.append(f"{oid} 下单行时刻 {下[0][2]} ≠ 订单时刻")
            if not any(r[3] == K.进入详情 and r[5] == 下[0][5] and r[2] < 下[0][2] for r in 会[下[0][0]]):
                bad.append(f"{oid} 下单前同一次里没进过那件的详情")
        elif 下:
            bad.append(f"别渠道订单 {oid} 在小程序里有「下单」行")
    # 每次会话内:进入详情 / 离开详情成对、离开 - 进入 = dwell
    for sid, rs in 会.items():
        进 = [r for r in rs if r[3] == K.进入详情]
        离 = [r for r in rs if r[3] == K.离开详情]
        if len(进) != len(离):
            bad.append(f"{sid} 进详情 {len(进)} 次、离开 {len(离)} 次"); break
        for a, b in zip(进, 离):
            if (dt.datetime.strptime(b[2], _F) - dt.datetime.strptime(a[2], _F)).seconds != b[6]:
                bad.append(f"{sid} 离开 - 进入 ≠ 停留秒"); break
    if any(r[5] == "P99" for r in 行):
        bad.append("待上架的商品被看了")
    没买 = [r for r in 行 if r[3] == K.进入列表]
    if any(r[2] >= 今.strftime("%Y-%m-%d") for r in 行 if r[7] is None and not any(
            x[3] == K.下单 for x in 会[r[0]])):
        bad.append("「看了没买」落到了世界今天或之后")
    if not 没买:
        bad.append("一次「进入列表」都没有 —— 入口分布没起作用")
    有人 = {r[1] for r in 行}
    缺 = [cid for cid, d in 客 if d < 今 - dt.timedelta(days=1) and cid not in 有人]
    if K.每人至少进来一次 and 缺:
        bad.append(f"保底:{len(缺)} 个客户一次都没进来过(如 {缺[:3]})—— 「给所有顾客都模拟上」没兑现")
    if not any(r[3] == K.收藏 for r in 行):
        bad.append("一行「收藏」都没有 —— 收藏没铺上")
    return bad


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        b = _自测()
        for x in b:
            print(f"  ❌ {x}")
        print("❌ 自测没过" if b else "✅ 浏览造数自测:对得上订单 / 时间先后 / 停留成对 / 不看待上架 / 不落未来 / 确定性")
        sys.exit(1 if b else 0)
    sys.exit(铺())
