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
import protect as PR
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan import dominators
from discover import creation_col

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
# 数据池要跟着源库的文字走。往一个 US/GB/DE/JP 的系统里灌「郭磊」,
# 结构上没错,但任何跟人名、排序、字符宽度有关的功能拿它测都是假的。
EN_FIRST = ["James", "Mary", "Liam", "Olivia", "Noah", "Emma", "Lucas", "Sophia",
            "Ethan", "Ava", "Mia", "Leo", "Hannah", "Yuki", "Kenji", "Anna"]
EN_LAST = ["Smith", "Johnson", "Müller", "Garcia", "Brown", "Wilson", "Tanaka",
           "Dubois", "Rossi", "Novak", "Silva", "Khan"]
STREET = ["文一西路", "解放路", "中山北路", "人民大道", "锦绣路", "长虹街", "望江东路"]
# 边界值:每一个都对应一类线上真出过的事故。
#
# **它也要跟着源库的文字走。** 往一个英文系统里注入「  张三  」测前后空格,
# 测的东西是对的,但样本不像它会收到的数据 —— 而边界值的全部价值就在于
# "它长得像真会出现的那种脏"。
# 例外是**非拉丁字符**那一条:在西文系统里它恰恰是正当的字符集测试(能不能存 CJK/emoji),
# 所以两种库里都保留。
_EDGE_ZH = [
    ("超长", "测试" * 60), ("emoji", "小王🧵🪡汉服"), ("前后空格", "  张三  "),
    ("单引号", "O'Brien 的马面裙"), ("换行", "第一行\n第二行"),
    ("空串", ""), ("全角数字", "１２３４５"),
]
_EDGE_EN = [
    ("超长", "Test" * 90), ("非拉丁", "Zoë 汉服🧵"), ("前后空格", "  John  "),
    ("单引号", "O'Brien & Sons"), ("换行", "line one\nline two"),
    ("空串", ""), ("全角数字", "１２３４５"),
]
EDGE_TEXT = _EDGE_ZH        # 默认中文;generate() 会按源库切换

# 边界值只往**自由文本**列掺,不往有格式契约的列掺。
# 第一版只掺 `text` 兜底列 —— 于是姓名列一个边界值都没有,
# 而「超长昵称撑破表格」「emoji 名字存不进 latin1」恰恰是最经典的两起线上事故。
# 反过来也不能一掺到底:往枚举列掺,方案自己派生的枚举断言会红;
# 往日期列掺,时间线断言会红。**造出来的脏数据必须是合法的脏,不然灌不进去,等于没测。**
EDGE_OK = ("text", "long_text", "cn_name", "address")

def rng_for(seed, *parts):
    return random.Random(f"{seed}::" + "::".join(str(p) for p in parts))


# 「这一列是批级的」—— 它的取值**按设计**要看整批行,不只看自己这一行。
# 写成显式清单而不是让 stable.py 扫出来:扫出来的清单会**把新冒出来的漂移当成现状接受**
# (和 samekey_check 的登记表同一个道理)。新加一种批级写法就得加进来,否则 stable 报红。
批级的 = {
    "fk":  "引用密度形状:哪个父亲带几个孩子,要把 n 个孩子分完才知道",
}
# 列名前缀是这几个的,也是批级的(时间线 / 起止 / 锚点 / 时间序都在改写整批)
批级改写 = ("__timeline", "__起止", "__锚点", "__时间序")


def 行rng(seed, tname, cname, 键, *extra):
    """**一行的值只由它自己的业务键决定,不由它在这批里排第几决定。**

    原来是每列一个 rng 顺着抽:`r = rng_for(seed, 表, 列)` 然后 `for i, row in ...`。
    列级是隔离的(加一张表不影响别的表),**行级不是** ——
    往中间插一行、或者同一批键换个顺序,后面每一行的值全跟着挪。

    这个形状在澜绣云裳真的炸过:商品图的颜色按 `插入序号 * 3 + hash(款号)` 取,
    改了两行造数据的代码,**38 款里 22 款换了颜色,其中 6 款是已经交付出去的图**。
    图在外面已经是事实了,数据却自己动了。

    代价:每行一个 Random 对象。百万行时这是真实开销,但换来的是
    「昨天复现 bug 的那批数据,今天加了几行之后还是那批」——
    而这正是假数据存在的理由(见本文件开头「造完这批 bug 就不见了」)。
    """
    return rng_for(seed, tname, cname, "行", 键, *extra)


def _边界_按键(seed, tname, cname, 键们, kinds, rate):
    """边界值落在哪几行 —— **按键排名选,不按下标洗牌选。**

    原来是 `idx=list(range(n)); r.shuffle(idx)`,选出来的是「第 3 行、第 17 行」——
    同一批键换个顺序,脏数据就换了人。改成按 `(种子,表,列,键)` 给每个键算一个排名、
    取前几名:**选谁不再看顺序**。

    要同时满足的两个目标没变(这是上一版用一次真 MySQL 跑出来的教训:
    每行 5% 概率去赌覆盖率,32 行客户里只中了一个 emoji):

      (a) **覆盖** —— 每一种边界值至少出现一次(行数容得下的前提下)
      (b) **比例** —— 大批量时脏数据要占到 rate,不然压力测试里它们等于不存在

    先按 (a) 定保底条数,再按 (b) 往上加,种类轮着分配。
    硬上限四分之一:边界值再重要也不能喧宾夺主,不然它就不叫边界了。
    """
    n = len(键们)
    if not kinds or not n or not rate:
        return {}
    guaranteed = min(len(kinds), max(1, n // 4))
    total = max(guaranteed, min(int(n * rate), max(1, n // 4) * len(kinds)))
    排 = sorted(键们, key=lambda k: rng_for(seed, tname, cname, "边界", k).random())
    return {k: kinds[i % len(kinds)] for i, k in enumerate(排[:min(total, n)])}

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

# **这批数据的「今天」。** 由 `generate()` 从方案里取,方案在出的那一刻就把它钉死了。
# 为什么是模块级而不是层层传参:`_dt` 被 `_value` 和 `_fsm_fix` 两条路径调到,
# 后者拿不到 plan 也拿不到 ctx —— 而「时间原点」这种东西**漏掉一处就等于没钉**,
# 所以宁可用一个进程内的锚点,也不要一条参数链上少传一处还没人发现。
_今天 = None


def _锚日():
    if _今天:
        try: return datetime.date.fromisoformat(_今天[:10])
        except ValueError: pass
    # 方案里没钉(老方案文件)—— **明说,不静默退回机器的今天**
    raise SystemExit("❌ 这份方案没有「今天」这一项,而日期列要拿它当上界。\n"
                     "   退回机器的今天会让同一份方案今天和明天造出不同的数据。\n"
                     "   办法:重新出一次方案(plan),它会把当天钉进去。")


def _dt(r, lo=None, hi=None):
    hi = hi or _锚日()
    lo = lo or (hi - datetime.timedelta(days=730))
    d = lo + datetime.timedelta(days=r.randint(0, max(1, (hi - lo).days)))
    return d

# ---------- 单列生成 ----------

def _value(g, r, ctx):
    k = g["gen"]
    if k == "cn_name":
        if not ctx.get("中文库", True):
            return f"{r.choice(EN_FIRST)} {r.choice(EN_LAST)}"
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
        v = min(v, (rg.get("max") or v * 5) * 1.5)
        # **金额列是整数时不能出小数。** `amount_cents` 存的是分,
        # 造出 28363.32 分既不合类型也不合语义 —— SQLite 宽容不报错,MySQL 会截断。
        # 语义(这是钱)和类型(这列是整数)都要听,不能只听语义。
        return int(round(v)) if g.get("kind") == "int" else round(v, 2)
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
    if k == "coded_id":
        f = g.get("编号格式")
        if f:   # 学源库的格式:前缀 + 分隔符 + 位数
            return f'{f["前缀"]}{f["分隔"]}{r.randint(0, 10 ** f["位数"] - 1):0{f["位数"]}d}'
        return f"REF{r.randint(100000,999999)}"
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


def _not_before(base, cols, col, r, max_days=30, strict=False):
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
    if nv > str(base) or (nv == str(base) and not strict): return nv
    # strict:必须**严格晚于**。起止时间就是这种 —— 接口判的是 `end <= start` 就拒,
    # 相等也不行。兜底退回"等于"在「不早于」下是对的,在「必须晚于」下还是错的。
    # **同一个词在两条规则下的边界不一样,兜底也得跟着分。**
    if not strict: return str(base)
    d2 = datetime.date.fromisoformat(str(base)[:10]) + datetime.timedelta(days=1)
    return d2.isoformat() if cols[col]["gen"] == "date" else \
        f"{d2.isoformat()} {r.randint(8,21):02d}:{r.randint(0,59):02d}:00"


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


def _fsm_fix(rows, cname, g, cols, 造rng):
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
    anchor_col = creation_col([c for c in cols if c not in ts.values()],
                              {c: cols[c]["gen"] for c in cols})
    for row in rows:
        # **按这一行的键取 rng**,不是整批顺着抽 —— 见 `行rng` 的说明
        r = 造rng(row.get("__键"))
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

def existing_values(conn, tname, cname, cap=50000):
    """库里这一列**已经有的**值。唯一性要跟它们比,不能只跟本次造的比。

    NULL 不算:SQL 的 UNIQUE 允许多个 NULL。
    """
    if conn is None: return set()
    try:
        return {r[0] for r in conn.q(
            f"select {conn.ident(cname)} from {conn.ident(tname)} "
            f"where {conn.ident(cname)} is not null limit {cap}")}
    except Exception:
        return set()


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


def generate(plan, conn=None, edge_rate=0.05, sink=None, log=lambda *a: None):
    """按方案造数据。返回 {表名: [行字典]}。表按方案里的拓扑顺序生成。

    ## sink:把「造」和「灌」串成流水线

    不给 sink 时,所有表所有行会一直留在内存里 —— 这是个 **O(总行数 × 总列数)** 的设计。
    实测约 0.87 KB/行:88 万行吃掉 764 MB,而这个工具的核心主张恰恰是「要多少有多少」。
    在几百行上完全看不出来,正是那种**小规模下永远正确**的架构决定。

    给了 sink,每造完一张表就交出去灌,然后**只留下会被子表用到的那几列**。
    一张 36 列的客户表通常只有 2-3 列被指过来,剩下的当场释放。
    """
    seed = plan["seed"]
    global _今天
    _今天 = plan.get("今天")
    保护 = plan.get("protect") or []
    edges = _EDGE_ZH if plan.get("中文库", True) else _EDGE_EN
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
            if plan.get("__键序") == "逆":
                # 只给 stable.py 用:**同一批键换个顺序**再造一遍。
                # 不是「多造一行」—— 追加在末尾时,前面每一行的流位置都没变,
                # 按下标取值的列照样对得上,**测不出东西来**。要让同一个键落到不同的行位。
                pkvals = list(reversed(pkvals))
            for i, row in enumerate(rows): row[pkcol] = pkvals[i]
            manifest[tname] = {"pk": pkcol, "values": pkvals}
        # 这一行的**业务键** —— 下面每一列的取值都从它派生,而不是从 i 派生
        键们 = pkvals if pkcol else [f"#{i}" for i in range(n)]
        # 挂到行上:后面四段时间修正是 `for row in rows`,拿不到下标,
        # 而它们**每一段都在按行序抽随机数** —— 不挂键就只能改一半。
        for i, row in enumerate(rows): row["__键"] = 键们[i]

        for cname, g in cols.items():
            if cname == pkcol: continue
            r = rng_for(seed, tname, cname)

            if g["gen"] == "fk":
                parent = g["table"]
                if parent == tname:
                    # 自引用(上级分类 / 父母是谁)。只能指向**本表更早的那些行** ——
                    # 指向后面的行会在数据里造出真正的环,任何递归查询都会打转。
                    # 头 20% 的行留空当根节点,不然一棵树没有根。
                    if not pkcol:
                        # 无主键表的自引用:没有可引用的值。**要显式置空,不能 continue** ——
                        # continue 会让这一列在每一行里都不存在,于是灌入时被整列丢掉。
                        for row in rows: row[cname] = None
                        continue
                    if g.get("unique"):
                        # 唯一的自引用:每行指向**前一行**,既不重复又不成环。
                        # (随机从前面挑会重复 —— 唯一约束当场炸。
                        #  这是同一个坑的第二处:外键分支和自引用分支各写了一遍,
                        #  我只修了前一处。**同样的逻辑写两遍,就会有一处是旧的。**)
                        for i, row in enumerate(rows):
                            row[cname] = pkvals[i - 1] if i else None
                        continue
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
                    # **受保护的行不许被指向。** 指过去就等于把夹具卷进新数据的语义里 ——
                    # 给一个「量体记录不全」的客户挂上新订单,那条判责用例的真值就翻了,
                    # 而**没有任何东西会变红**。
                    # ⚠️ 只在这里剔,不在 existing_values 里剔:唯一性要跟**库里真实存在的值**比,
                    # 受保护的行也占着位置。同一批值,两处用途正好相反。
                    if 保护:
                        pv, 剔 = PR.过滤外键池(conn, 保护, parent, g["column"], pv)
                        if 剔: log(f"    保护:{tname}.{cname} 的取值池剔掉 {剔} 个受保护的 {parent}")
                else: pv = []
                # 成环时先留空,全部灌完再回填(见 load 的第二阶段)
                if g.get("deferred") or not pv:
                    for row in rows: row[cname] = None
                    continue
                if g.get("unique"):
                    # **schema 明写的 UNIQUE,压过推断出来的「形状」。**
                    # 唯一和外键本身不矛盾(1:1 关系是合法的);矛盾的是唯一
                    # 和**按形状分配** —— 形状说「一个父亲 1-3 个孩子」,
                    # 唯一说「最多 1 个」。所以唯一外键必须**无放回**地取。
                    #
                    # 这个 bug 是这么暴露的:另一条线给 staff 加了
                    # `login_name TEXT UNIQUE`,而种子里登录名就等于工号,
                    # 于是值重叠 100%,推断层把它认成「指向工号的外键」,
                    # 外键分支 `continue` 掉、唯一性那段根本没跑到,当场 IntegrityError。
                    # **一个明写的约束,被一个推断出来的结论盖过去了。**
                    used = existing_values(conn, tname, cname)
                    avail = [v for v in pv if v not in used]
                    r.shuffle(avail)
                    nullable = g.get("nullable", True)
                    for i, row in enumerate(rows):
                        if i < len(avail): row[cname] = avail[i]
                        elif nullable:     row[cname] = None      # 取不够就留空,NULL 不受唯一约束
                        else:
                            raise SystemExit(
                                f"{tname}.{cname} 是唯一外键,但父表只剩 {len(avail)} 个"
                                f"没被占用的值,不够造 {n} 行,而这一列又不可为空。\n"
                                f"办法:把这张表的行数调小,或者确认这条外键是不是推错了"
                                f"(唯一列指向另一列,常常只是取值恰好相等)。")
                    continue
                pool = _fk_pool(g.get("shape"), pv, n, r)
                for i, row in enumerate(rows): row[cname] = pool[i]
                continue

            if g["gen"] == "fsm":
                states = [s for s in ({x for ab in g["transitions"] for x in ab}
                                      | set(g["start"]))]
                w = {s: (g.get("dist") or {}).get(s, 0.01) for s in states}
                for i, row in enumerate(rows):
                    row[cname] = _weighted(行rng(seed, tname, cname, 键们[i]), w)
                continue

            nr = g.get("null_rate") or 0
            # **按键选,不按下标选** —— 见 `_边界_按键` 和 `行rng`
            slots = (_边界_按键(seed, tname, cname, 键们, [v for _n, v in edges], edge_rate)
                     if (g["gen"] in EDGE_OK and not g.get("unique") and edge_rate) else {})
            for i, row in enumerate(rows):
                键 = 键们[i]
                rr = 行rng(seed, tname, cname, 键)
                if nr and rr.random() < nr:
                    row[cname] = None; continue
                ctx = row.setdefault("__ctx", {})
                ctx["中文库"] = plan.get("中文库", True)
                if 键 in slots:
                    row[cname] = _cap(slots[键], g)
                else:
                    row[cname] = _cap(_value(g, rr, ctx), g)
            if g.get("unique"):
                # 和**库里已有的**比,不能只跟本次造的比 ——
                # 灌进的是一张已经有数据的表,只在自己这批里去重是不够的。
                seen = set(existing_values(conn, tname, cname))
                r2 = rng_for(seed, tname, cname, "uniq")
                for row in rows:
                    v = row[cname]
                    if v is None: continue          # NULL 不受唯一约束,多个 NULL 合法
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
            # 每行独立抽一个组合 —— 独立,所以能按键抽(不是批级的)
            for i, row in enumerate(rows):
                rj = 行rng(seed, tname, "联合", 键们[i], "|".join(gcols))
                pick = rj.choices(tuples, weights=weights, k=1)[0]
                for c, v in zip(gcols, pick): row[c] = v

        # 状态机改写要在时间线修正**之前** —— 它写的是「哪些时间戳该有值」,
        # 时间线修正管的是「有值的那些先后对不对」。顺序反了会把状态机写的空值填回去。
        for cname, g in cols.items():
            if g["gen"] == "fsm":
                _fsm_fix(rows, cname, g, cols,
                         lambda 键, _c=cname: 行rng(seed, tname, _c, 键, "状态机"))

        # 时间线修正:让 created ≤ paid_at ≤ shipped_at ≤ …
        # 这一步不是锦上添花 —— 方案里自动派生的时间线断言,靠它才通得过。
        present = [c for c in TIME_ORDER if c in cols and cols[c]["gen"] in ("date", "datetime")]
        if len(present) > 1:
            for row in rows:
                last = None
                for c in present:
                    v = row.get(c)
                    if v is None: continue
                    if last and str(v) < str(last):
                        row[c] = _not_before(last, cols, c,
                                             行rng(seed, tname, "__timeline", row["__键"], c), 20)
                    last = row[c]
        # 起止成对的列:结束不得早于开始。
        # 这条是**接口照出来的**:预约表的 start_ts / end_ts 既不以 _at 结尾、
        # 也不在写死的那张时间线表里,于是两套时间修正一条都没覆盖到它们,
        # 造出来 4 条「结束早于开始」的预约 —— 数据库照单全收,写接口当场拒绝。
        # 直连那条路对此完全无感,因为库里它们只是两个字符串。
        #
        # ⚠️ **断言按列名推,修正按类型推 —— 两边判据不一致就会漏。**
        # 2026-09-21 bench 抓到:`shift_tpl.start_t / end_t` 是**时刻文本**
        # (「09:00」这种,不是日期),于是下面这个 `gen in (date, datetime)`
        # 把它们挡在外面,而**派生断言那边只看列名,照样给它们生成了
        # 「end 不该早于 start」**。结果是工厂造出了自己断言不允许的数据 ——
        # 报出来是「我弄脏的 1 条」,而那正是这个工具最不能出的错。
        #
        # 修法:日期那一类照旧往后推;**别的可比类型直接对调** ——
        # 对调不改动任何取值,只换个位置,分布一个字都不变。
        pairs, 对调 = [], []
        for c in cols:
            if "start" in c.lower():
                e = c.lower().replace("start", "end")
                m = next((x for x in cols if x.lower() == e), None)
                if not m:
                    continue
                if cols[c]["gen"] in ("date", "datetime") \
                   and cols[m]["gen"] in ("date", "datetime"):
                    pairs.append((c, m))
                elif cols[c]["gen"] == cols[m]["gen"]:
                    # 同类型的一对(时刻文本 / 数字区间都算),用对调兜住
                    对调.append((c, m))
        for a, b in 对调:
            for row in rows:
                x, y = row.get(a), row.get(b)
                if x is not None and y is not None and str(y) < str(x):
                    row[a], row[b] = y, x
        if pairs:
            for row in rows:
                for a, b in pairs:
                    if row.get(a) and row.get(b) and str(row[b]) <= str(row[a]):
                        row[b] = _not_before(row[a], cols, b,
                                             行rng(seed, tname, "__起止", row["__键"], b),
                                             2, strict=True)

        # 兜底:任何 *_at 都不该早于**建档时间那一列**(名字是推出来的,不写死)。
        # 状态机管得住它认领的那几列,管不住剩下的(synced_at / on_shelf_at / handled_at…)——
        # 那些是各自独立抽的,自然会掉到下单时间前面。
        # 时间原点这件事得**全表统一**兜一次,不能指望每个局部规则各自记得。
        base_c = creation_col(list(cols), {c: cols[c]["gen"] for c in cols})
        if base_c:
            ats = [c for c in cols if c != base_c and (c.endswith("_at") or c.endswith("_time"))
                   and cols[c]["gen"] in ("date", "datetime")]
            for row in rows:
                base = row.get(base_c)
                if not base: continue
                for c in ats:
                    v = row.get(c)
                    if v is None or str(v) >= str(base): continue
                    row[c] = _not_before(base, cols, c,
                                         行rng(seed, tname, "__锚点", row["__键"], c), 30)

        # 源库统计出来的时间先后。**必须排在所有时间修正的最后。**
        #
        # 排序依据是**谁的约束更具体**:统计出来的成对先后(源库 88 行无一倒挂)
        # 比「都不早于建档时间」这条通用兜底具体得多,所以它说了算。
        # 放在前面会被兜底推翻 —— 兜底把某一列往后挪一个随机天数,
        # 刚排好的成对先后就散了。规则本身都对,顺序错了就互相拆台。
        # 它只把值往后推,不会破坏"不早于建档时间"(建档时间是链的头)。
        #
        # 多跑几遍:a≤b、b≤c 是一条链,一遍只推平相邻的一对,链长几步就要几遍。
        seq = tp.get("时间序") or []
        if seq:
            for _pass in range(5):
                for o in seq:
                    a, b = o["先"], o["后"]
                    if a not in cols or b not in cols: continue
                    if cols[b]["gen"] not in ("date", "datetime"): continue
                    for row in rows:
                        if row.get(a) and row.get(b) and str(row[b]) < str(row[a]):
                            row[b] = _not_before(row[a], cols, b,
                                                 行rng(seed, tname, "__时间序", row["__键"], b), 10)

        for row in rows: row.pop("__ctx", None); row.pop("__键", None)
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
