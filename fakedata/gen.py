#!/usr/bin/env python3
"""生成器 —— 照方案造数据。**确定性**是这一层唯一不能让步的性质。

## 为什么种子这么重要

假数据最常见的失败不是「造得不像」,是「**造完这批,bug 就不见了**」。
测试跑红了,你想复现,重新造一批 —— 数据全变了,红的那条也没了。
于是这个 bug 变成玄学,没人再敢碰。

所以每一列的随机数发生器都由 `(种子, 表名, 列名)` 单独播种:
  · 同一个种子 → 永远同一批数据
  · 给方案**新加一张表,不会让原来那些表的数据变样** ——
    如果所有列共用一个全局 rng,插入顺序一变,后面全跟着漂。
    这条差别在小 demo 上看不出来,在「加了张表之后昨天的复现用例失效了」时要人命。

## 引用密度:照形状分配,不是平均分

推断层量出来的形状(60% 的父亲一个孩子都没有 / 10% 有 50 个以上),在这里落地。
平均分配的假数据测不出 N+1 查询、测不出空状态、测不出分页 ——
而这三类恰恰是线上最常见的问题。

## 边界值:5% 的脏数据,是这批数据里最值钱的部分

正常路径谁都测得到。真正会炸的是超长昵称把表格撑破、emoji 存进 latin1 字段、
前后空格让精确匹配失效、单引号进了拼接的 SQL。
所以文本列默认掺 5% 的边界值 —— 它们**必须**是合法数据(不违反非空/唯一/长度),
否则灌不进去,等于没测。
"""
import os, sys, math, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan import dominators

# ---------- 中文数据池 ----------
XING = "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
MING = "秀英伟芳娜敏静丽强磊洋勇艳杰娟涛明超霞平刚桂英玉兰建华文博宇轩子涵欣怡梓晴一诺沐辰"
# 省-市-区 三级要**对得上**。造出「浙江省·成都市」这种数据,
# 任何按地域筛选的功能测起来都是假的。
REGION = {
    "浙江": {"杭州": ["西湖区", "拱墅区", "余杭区"], "宁波": ["海曙区", "鄞州区"]},
    "江苏": {"苏州": ["姑苏区", "工业园区"], "南京": ["鼓楼区", "秦淮区"]},
    "四川": {"成都": ["武侯区", "锦江区", "青羊区"]},
    "陕西": {"西安": ["雁塔区", "碑林区"]},
    "广东": {"广州": ["天河区", "越秀区"], "深圳": ["南山区", "福田区"]},
    "上海": {"上海": ["徐汇区", "静安区", "浦东新区"]},
    "北京": {"北京": ["朝阳区", "海淀区", "东城区"]},
    "湖北": {"武汉": ["武昌区", "江汉区"]},
}
STREET = ["文一西路", "解放路", "中山北路", "人民大道", "锦绣路", "长虹街", "望江东路"]
# 边界值:每一个都对应一类线上真出过的事故
EDGE_TEXT = [
    ("超长", "测试" * 60),                    # 表格撑破 / varchar 截断
    ("emoji", "小王🧵🪡汉服"),                 # 字符集不是 utf8mb4 就当场炸
    ("前后空格", "  张三  "),                  # 精确匹配失效
    ("单引号", "O'Brien 的马面裙"),            # 字符串拼接 SQL
    ("换行", "第一行\n第二行"),                # CSV 导出错行
    ("空串", ""),                             # 和 NULL 不是一回事
    ("全角数字", "１２３４５"),                 # 数字校验漏
]

# 边界值只往**自由文本**列掺,不往有格式契约的列掺。
# 第一版只掺 `text` 兜底列 —— 于是姓名列一个边界值都没有,
# 而「超长昵称撑破表格」「emoji 名字存不进 latin1」恰恰是最经典的两起线上事故。
# 反过来也不能一掺到底:往枚举列掺,方案自己派生的枚举断言会红;
# 往日期列掺,时间线断言会红。**造出来的脏数据必须是合法的脏,不然灌不进去,等于没测。**
EDGE_OK = ("text", "long_text", "cn_name", "address")

def _edge_slots(r, n, kinds, rate):
    """给每一种边界值**指定行号**,而不是每行掷一次骰子。

    第一版是「每行 5% 概率掺一个随机边界值」。在真 MySQL 上跑完一看:
    32 行客户里只中了一个 emoji,超长和前后空格一个都没出现。
    **边界值的全部意义就是覆盖,而用概率去赌覆盖率,是把手段和目的搞反了。**
    行数越少漏得越狠 —— 而小批量恰恰是人跑得最勤的那种。

    改成:先算出这批数据能容下几个边界值(不超过 rate 的两倍,也不超过 25%),
    然后**按种类轮着放**,保证在容得下的前提下每种至少出现一次。
    位置由种子决定,所以仍然是确定性的。
    """
    # 两个目标会打架,都要满足:
    #   (a) **覆盖** —— 每一种边界值至少出现一次(行数容得下的前提下)
    #   (b) **比例** —— 大批量时脏数据要占到 rate,不然压力测试里它们等于不存在
    # 所以:先按 (a) 定下保底条数,再按 (b) 往上加,位置轮着分配 ——
    # 轮着分配天然保证了「先覆盖全,再各自加量」。
    # 硬上限是四分之一:边界值再重要也不能喧宾夺主,不然它就不叫边界了。
    guaranteed = min(len(kinds), max(1, n // 4))
    total = max(guaranteed, min(int(n * rate), max(1, n // 4) * len(kinds)))
    idx = list(range(n)); r.shuffle(idx)
    return {idx[i]: kinds[i % len(kinds)] for i in range(min(total, n))}

def rng_for(seed, *parts):
    return random.Random(f"{seed}::" + "::".join(str(p) for p in parts))

def _lognormal(r, p50, p90):
    """按 p50/p90 拟合长尾。金额、时长都是长尾 —— 用均值造出来的数据全挤在中间,
    压根测不出「那个花了 8 万的大单页面会不会崩」。"""
    if not p50 or p50 <= 0: return abs(r.gauss(100, 50))
    if not p90 or p90 <= p50: p90 = p50 * 3
    mu = math.log(p50)
    sigma = max(0.05, (math.log(p90) - mu) / 1.2816)
    return math.exp(r.gauss(mu, sigma))

def _weighted(r, dist):
    keys = list(dist); w = [max(dist[k], 1e-6) for k in keys]
    return r.choices(keys, weights=w, k=1)[0]

def _dt(r, lo=None, hi=None):
    hi = hi or datetime.date.today()
    lo = lo or (hi - datetime.timedelta(days=730))
    d = lo + datetime.timedelta(days=r.randint(0, max(1, (hi - lo).days)))
    return d

# ---------- 单列生成 ----------

def _value(g, r, ctx):
    k = g["gen"]
    if k == "cn_name":
        return r.choice(XING) + "".join(r.choice(MING) for _ in range(r.choice([1, 1, 2])))
    if k == "cn_mobile":
        return "1" + r.choice("3567889") + "".join(str(r.randint(0, 9)) for _ in range(9))
    if k == "email":
        return f"u{r.randint(1000,999999)}@{r.choice(['qq.com','163.com','gmail.com','foxmail.com'])}"
    if k in ("province", "city", "district"):
        # 三者要一致 —— 同一行里第一次抽定省市区,后面两列直接取
        if "region" not in ctx:
            p = r.choice(list(REGION)); c = r.choice(list(REGION[p]))
            ctx["region"] = (p, c, r.choice(REGION[p][c]))
        return ctx["region"]["province city district".split().index(k)]
    if k == "address":
        if "region" not in ctx:
            p = r.choice(list(REGION)); c = r.choice(list(REGION[p]))
            ctx["region"] = (p, c, r.choice(REGION[p][c]))
        p, c, d = ctx["region"]
        return f"{p}{c}市{d}{r.choice(STREET)}{r.randint(1,999)}号{r.randint(1,30)}幢{r.randint(101,2508)}"
    if k == "money":
        rg = g.get("range") or {}
        v = _lognormal(r, rg.get("p50"), rg.get("p90"))
        return round(min(v, (rg.get("max") or v * 5) * 1.5), 2)
    if k == "percent":  return round(r.uniform(0, 1), 3)
    if k == "small_int":
        rg = g.get("range") or {}
        return r.randint(int(rg.get("min", 0) or 0), int(rg.get("max", 9) or 9))
    if k == "number":
        rg = g.get("range") or {}
        lo, hi = rg.get("min", 0) or 0, rg.get("max", 100) or 100
        if isinstance(lo, float) or isinstance(hi, float):
            return round(r.uniform(float(lo), float(hi)), 2)
        return r.randint(int(lo), int(hi))
    if k in ("date", "datetime"):
        rg = g.get("range") or {}
        lo = hi = None
        try:
            if rg.get("min"): lo = datetime.date.fromisoformat(str(rg["min"])[:10])
            if rg.get("max"): hi = datetime.date.fromisoformat(str(rg["max"])[:10])
        except ValueError: pass
        d = _dt(r, lo, hi)
        if k == "date": return d.isoformat()
        return f"{d.isoformat()} {r.randint(8,21):02d}:{r.randint(0,59):02d}:{r.randint(0,59):02d}"
    if k == "enum":     return _weighted(r, g["dist"]) if g.get("dist") else "未知"
    if k == "url":      return f"/static/{r.randint(1000,9999)}.jpg"
    if k == "json_blob":return '{"k":%d}' % r.randint(1, 99)
    if k == "coded_id": return f"REF{r.randint(100000,999999)}"
    if k == "long_text":
        return r.choice(["客户对袖型有特别要求,已备注给版房。",
                         "量体数据偏差较大,建议复量后再开工。",
                         "婚期临近,工期已排加急。", "面料到货延迟,已知会顾问。"])
    ln = (g.get("len") or {}).get("p50") or 8
    return "".join(r.choice("甲乙丙丁戊己庚辛壬癸ABCDEFGH0123456789") for _ in range(max(2, int(ln))))


def _cap(v, g):
    """长度上限:MySQL 的 varchar(N) 超了会**截断或报错**,SQLite 不管。
    边界值的意义是「合法但极端」,不是「灌不进去」—— 所以必须在这里收住。"""
    m = g.get("maxlen")
    return v[:m] if (m and isinstance(v, str) and len(v) > m) else v


def _pk_values(plan, tname, tp, n):
    """主键 = 假数据的**标记**。带前缀的 id 让「清干净」变成一条 DELETE。

    整数主键没法加前缀,改用一个约定的高位段(9 开头的十位数)。
    两种都会同时记进 manifest —— 前缀只是方便人肉排查,真正的回滚依据是 manifest。
    """
    g = tp["columns"].get(tp["pk"][0], {}) if tp["pk"] else {}
    pre = plan["marker"]["prefix"]
    if g.get("style") == "int_seq" or g.get("gen") == "pk" and g.get("style") == "int_seq":
        return [900000000 + i for i in range(1, n + 1)]
    abbr = "".join(ch for ch in tname.upper() if ch.isalnum())[:6]
    return [f"{pre}{abbr}{i:05d}" for i in range(1, n + 1)]


def _fk_pool(shape, parents, n, r):
    """按形状把 n 个孩子分给 parents。

    形状是「多少比例的父亲有几个孩子」,不是平均数。先按比例决定每个父亲带几个,
    再按总数缩放对齐 n。缩放会有误差,最后多退少补 —— 补的时候优先补给
    已经有孩子的父亲,免得把「60% 的父亲零孩子」这个最要紧的特征冲掉。
    """
    if not parents: return []
    if not shape:
        return [r.choice(parents) for _ in range(n)]
    RANGE = {"0": (0, 0), "1-3": (1, 3), "4-10": (4, 10), "11-50": (11, 50), "50+": (51, 120)}
    ps = list(parents); r.shuffle(ps)
    counts, i = [], 0
    for bucket, frac in shape.items():
        k = int(round(frac * len(ps)))
        lo, hi = RANGE.get(bucket, (1, 3))
        for _ in range(k):
            if i >= len(ps): break
            counts.append([ps[i], r.randint(lo, hi)]); i += 1
    for j in range(i, len(ps)): counts.append([ps[j], 0])
    tot = sum(c for _p, c in counts) or 1
    scale = n / tot
    for c in counts: c[1] = int(round(c[1] * scale))
    pool = [p for p, c in counts for _ in range(c)]
    nonzero = [p for p, c in counts if c > 0] or ps
    while len(pool) < n: pool.append(r.choice(nonzero))
    r.shuffle(pool)
    return pool[:n]


def _not_before(base, cols, col, r, max_days=30):
    """造一个「不早于 base」的时间值。**这个函数存在的理由是它被写错过两次。**

    朴素写法是「取 base 的日期部分,加 0..N 天,再随机一个时分」。
    偏移抽到 0 天、而 base 带时分秒时,新值的时分仍然可能更早 —— 差几个小时,
    刚好还是违反「不早于」。概率很低,所以**在几十行的数据上根本不出现**:
    scale=1(26 行)一次没有,scale=5(130 行)就有一条。

    第一次在锚点兜底那里修好了,时间线修正那里**没跟着改** ——
    两处各写一遍同样的逻辑,就一定会有一处是旧的。
    所以收成一个函数:兜不住就直接取 base 本身,相等不违反「不早于」。
    """
    try:
        d = datetime.date.fromisoformat(str(base)[:10]) + \
            datetime.timedelta(days=r.randint(0, max_days))
    except ValueError:
        return base
    nv = d.isoformat() if cols[col]["gen"] == "date" else \
        f"{d.isoformat()} {r.randint(8,21):02d}:{r.randint(0,59):02d}:00"
    return nv if nv >= str(base) else str(base)


def _depths(start, trans):
    """每个状态离起点几步 —— 决定时间戳的先后。"""
    d, frontier, k = {s: 0 for s in start}, list(start), 0
    while frontier and k < 40:
        k += 1; nxt = []
        for n in frontier:
            for a, b in trans:
                if a == n and b not in d: d[b] = k; nxt.append(b)
        frontier = nxt
    return d


def _fsm_fix(rows, cname, g, cols, r):
    """把状态和时间戳绑在一起 —— 这是「语义像」和「结构像」的分界。

    统计层能造出「状态分布跟源库一样」的数据,但它是**逐列独立**抽的:
    状态抽到「已发货」,付款时间那一列另抽一次,可能是空的。
    于是库里躺着一批「已发货但没付过款」的订单 —— 数据库完全允许,业务上不可能。
    你拿这种数据去测,会花半天 debug 一个根本不存在的 bug。

    这里按状态机改写:到达该状态的**必经**状态,时间戳依次填上、时间递增;
    没走到的那些,时间戳留空。必经关系用支配点算,不是可达性 ——
    否则「从待付款直接取消」的订单会被要求有付款时间。
    """
    trans, start, ts = g["transitions"], g["start"], g["timestamps"]
    if not ts: return
    depth = _depths(start, trans)
    # **下单时间是这一行的时间原点。** 一张表可以有好几个状态机(订单状态、生产状态、
    # 退款状态),它们各管各的时间戳、互相不知道对方存在 ——
    # 于是生产完成时间会被排到下单时间之前。荒谬,但每个状态机单看都是自洽的。
    # 找一个所有状态机都认的锚点,是唯一能让它们对齐的办法。
    anchor_col = next((c for c in ("created", "create_time", "created_at")
                       if c in cols and c not in ts.values()), None)
    for row in rows:
        st = str(row.get(cname))
        must = dominators(start, trans, st) & set(ts)
        order = sorted(must, key=lambda x: depth.get(x, 99))
        cur = None
        for stt in order:
            col = ts[stt]
            if cur is None:
                v = row.get(col) or (row.get(anchor_col) if anchor_col else None)
                try: cur = datetime.date.fromisoformat(str(v)[:10]) if v else _dt(r)
                except ValueError: cur = _dt(r)
            else:
                cur = cur + datetime.timedelta(days=r.randint(0, 12))
            row[col] = cur.isoformat() if cols[col]["gen"] == "date" else \
                f"{cur.isoformat()} {r.randint(8,21):02d}:{r.randint(0,59):02d}:00"
        for stt, col in ts.items():
            # 没走到那一步就该是空的。但**非空列不能置空** ——
            # 那会当场违反方案自己派生的「不可为空」断言,
            # 变成工具自己造出来的检查失败。
            if stt not in must and cols[col].get("nullable", True):
                row[col] = None


TIME_ORDER = ["created", "paid_at", "shipped_at", "done_at", "updated", "last_interact"]

def needed_columns(plan):
    """每张表**会被别人用到**的列:自己的主键,加上被别的表外键指过来的那些列。

    流式生成的关键就在这个集合。造完一张表之后,整行数据其实只剩两个用途:
    灌进库里(灌完就不需要了)、给子表当外键取值(只需要被指的那一列)。
    其余的列留在内存里纯属占地方。
    """
    need = {t: set(tp["pk"]) for t, tp in plan["tables"].items()}
    for t, tp in plan["tables"].items():
        for _cn, g in tp["columns"].items():
            if g["gen"] == "fk" and g.get("table") in need:
                need[g["table"]].add(g["column"])
    return need


def generate(plan, conn=None, edge_rate=0.05, sink=None):
    """按方案造数据。返回 {表名: [行字典]}。表按方案里的拓扑顺序生成。

    ## sink:把「造」和「灌」串成流水线

    不给 sink 时,所有表所有行会一直留在内存里 —— 这是个 **O(总行数 × 总列数)** 的设计。
    实测约 0.87 KB/行:88 万行吃掉 764 MB,而这个工具的核心主张恰恰是「要多少有多少」。
    在几百行上完全看不出来,正是那种**小规模下永远正确**的架构决定。

    给了 sink,每造完一张表就交出去灌,然后**只留下会被子表用到的那几列**。
    一张 36 列的客户表通常只有 2-3 列被指过来,剩下的当场释放。
    """
    seed = plan["seed"]
    need = needed_columns(plan) if sink else None
    made, manifest = {}, {}
    for tname in plan["order"]:
        tp = plan["tables"][tname]
        if tp.get("skip"):
            made[tname] = []; continue
        n = tp["count"]
        cols = tp["columns"]
        pkcol = tp["pk"][0] if tp["pk"] else None
        rows = [{} for _ in range(n)]

        pkvals = _pk_values(plan, tname, tp, n) if pkcol else []
        if pkcol:
            for i, row in enumerate(rows): row[pkcol] = pkvals[i]
            manifest[tname] = {"pk": pkcol, "values": pkvals}

        for cname, g in cols.items():
            if cname == pkcol: continue
            r = rng_for(seed, tname, cname)

            if g["gen"] == "fk":
                parent = g["table"]
                if parent == tname:
                    # 自引用(上级分类 / 父母是谁)。只能指向**本表更早的那些行** ——
                    # 指向后面的行会在数据里造出真正的环,任何递归查询都会打转。
                    # 头 20% 的行留空当根节点,不然一棵树没有根。
                    if not pkcol: continue
                    for i, row in enumerate(rows):
                        row[cname] = None if i < max(1, n // 5) else r.choice(pkvals[:i])
                    continue
                if parent in made and made[parent]:
                    pv = [x.get(g["column"]) for x in made[parent] if x.get(g["column"]) is not None]
                elif conn is not None:
                    try:
                        pv = [x[0] for x in conn.q(
                            f'select {conn.ident(g["column"])} from {conn.ident(parent)} '
                            f'where {conn.ident(g["column"])} is not null limit 20000')]
                    except Exception: pv = []
                else: pv = []
                # 成环时先留空,全部灌完再回填(见 load 的第二阶段)
                if g.get("deferred") or not pv:
                    for row in rows: row[cname] = None
                    continue
                pool = _fk_pool(g.get("shape"), pv, n, r)
                for i, row in enumerate(rows): row[cname] = pool[i]
                continue

            if g["gen"] == "fsm":
                states = [s for s in ({x for ab in g["transitions"] for x in ab}
                                      | set(g["start"]))]
                w = {s: (g.get("dist") or {}).get(s, 0.01) for s in states}
                for row in rows: row[cname] = _weighted(r, w)
                continue

            nr = g.get("null_rate") or 0
            slots = (_edge_slots(rng_for(seed, tname, cname, "边界"), n,
                                 [v for _n, v in EDGE_TEXT], edge_rate)
                     if (g["gen"] in EDGE_OK and not g.get("unique") and edge_rate) else {})
            for i, row in enumerate(rows):
                if nr and r.random() < nr:
                    row[cname] = None; continue
                ctx = row.setdefault("__ctx", {})
                if i in slots:
                    row[cname] = _cap(slots[i], g)
                else:
                    row[cname] = _cap(_value(g, r, ctx), g)
            if g.get("unique"):
                seen, r2 = set(), rng_for(seed, tname, cname, "uniq")
                for row in rows:
                    v = row[cname]
                    while v in seen:
                        v = _cap(str(_value(g, r2, {})) + str(r2.randint(10, 9999)), g)
                    seen.add(v); row[cname] = v

        # 联合抽样要在状态机改写**之前**:它定的是「这一行的各个状态分别是什么」,
        # 状态机再据此把时间戳对上。反过来的话状态机刚排好的时间戳会被换掉的状态作废。
        #
        # 为什么照真实出现过的组合抽,而不是各列独立抽:
        # 独立抽样天然造不出列与列之间的关系 —— 订单状态抽到「待付款」,
        # 生产状态另抽一次抽到「已生产」,于是**未付款却已经生产了**。
        # 照真实组合抽,一致性是白送的:不需要先判断出规则,也就不会判错。
        # 代价是**不会造出源库没见过的组合**,变化少一点 —— 测试数据要一致性,这个换法划算。
        for grp in tp.get("joint", []):
            gcols = [c for c in grp["columns"] if c in cols]
            if len(gcols) < 2 or not grp["dist"]: continue
            keep = [grp["columns"].index(c) for c in gcols]
            tuples = [[t[i] for i in keep] for t, _w in grp["dist"]]
            weights = [w for _t, w in grp["dist"]]
            rj = rng_for(seed, tname, "联合", "|".join(gcols))
            for row in rows:
                pick = rj.choices(tuples, weights=weights, k=1)[0]
                for c, v in zip(gcols, pick): row[c] = v

        # 状态机改写要在时间线修正**之前** —— 它写的是「哪些时间戳该有值」,
        # 时间线修正管的是「有值的那些先后对不对」。顺序反了会把状态机写的空值填回去。
        for cname, g in cols.items():
            if g["gen"] == "fsm":
                _fsm_fix(rows, cname, g, cols, rng_for(seed, tname, cname, "状态机"))

        # 时间线修正:让 created ≤ paid_at ≤ shipped_at ≤ …
        # 这一步不是锦上添花 —— 方案里自动派生的时间线断言,靠它才通得过。
        present = [c for c in TIME_ORDER if c in cols and cols[c]["gen"] in ("date", "datetime")]
        if len(present) > 1:
            rt = rng_for(seed, tname, "__timeline")
            for row in rows:
                last = None
                for c in present:
                    v = row.get(c)
                    if v is None: continue
                    if last and str(v) < str(last):
                        row[c] = _not_before(last, cols, c, rt, 20)
                    last = row[c]
        # 兜底:任何 *_at 都不该早于 created。
        # 状态机管得住它认领的那几列,管不住剩下的(synced_at / on_shelf_at / handled_at…)——
        # 那些是各自独立抽的,自然会掉到下单时间前面。
        # 时间原点这件事得**全表统一**兜一次,不能指望每个局部规则各自记得。
        if "created" in cols:
            rt = rng_for(seed, tname, "__锚点")
            ats = [c for c in cols if c.endswith("_at")
                   and cols[c]["gen"] in ("date", "datetime")]
            for row in rows:
                base = row.get("created")
                if not base: continue
                for c in ats:
                    v = row.get(c)
                    if v is None or str(v) >= str(base): continue
                    row[c] = _not_before(base, cols, c, rt, 30)

        for row in rows: row.pop("__ctx", None)
        if sink:
            sink(tname, rows)
            keep = need[tname]
            made[tname] = [{k: r[k] for k in keep if k in r} for r in rows]
        else:
            made[tname] = rows
    return made, manifest


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import schema as S, discover as D, plan as P
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = S.connect(os.path.join(root, "backend", "lanxiu.db"))
    sc = conn.reflect(); f = D.discover(conn, sc)
    pl = P.build(f, scale=0.05)
    a, _m = generate(pl, conn)
    b, _m = generate(pl, conn)
    same = all(a[t] == b[t] for t in a)
    print("确定性(同种子两次生成完全一致):", "✅" if same else "❌")
    for t in ("customer", "ordr", "wearer"):
        if t in a and a[t]:
            print(f"\n=== {t} 头两行 ===")
            for row in a[t][:2]:
                print({k: v for k, v in list(row.items())[:9]})
