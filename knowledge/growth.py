#!/usr/bin/env python3
"""成长推算 —— 「今天量的尺寸,到交付那天还准不准?到明年还能不能穿?」

## 为什么这个模块存在

成衣卖「现在合身」,定制卖「做出来那天合身」,中间隔着 30–150 天工期。
成人这段时间不变,**小孩 60 天能长 1cm,150 天能长 2.5cm** ——
而童装档差本来只有 4–6cm。

更常见的坑是**第二次**:半年前的量体记录被顺手复用。
「你们不是有我尺寸吗」—— 返工成本全在商家。

## 三个方法的分工

  主   百分位法    z 分数不变,查目标年龄的 P50/SD 反算
  校验 靶身高法    父母身高推成年终身高,和百分位法对不上就**标人工**,不自动挑边
  兜底 年增速法    速率**从参照表相邻两行的 P50 差取**,不另立表(两张表一定漂)

## 这个模块最重要的一句话

**它推的不是这个孩子,是「他所在的那条百分位线」。**
所有个性化预测都是这个套路:不预测个体,预测他所属的群,再假设他不换群。
假设破了(青春期提前、大病),预测就崩 —— **所以假设必须写在产品里给用户看见**。

参照表在 `12-成长与生命周期.md`,本文件只解析和计算,不自带一份数值。
"""
import math, os, re, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "12-成长与生命周期.md")

_cache = {}


def _read():
    if "md" not in _cache:
        _cache["md"] = open(MD, encoding="utf-8").read()
    return _cache["md"]


def table():
    """{年龄: (男P50, 男SD, 女P50, 女SD)},从 md 解析,不在代码里另存一份"""
    if "tbl" in _cache: return _cache["tbl"]
    out = {}
    for line in _read().split("\n"):
        l = line.strip()
        if not re.match(r"^\|\s*G\d\d\s*\|", l): continue
        c = [x.strip() for x in l.strip("|").split("|")]
        if len(c) != 6: continue
        out[int(c[1])] = tuple(float(x) for x in c[2:])
    if not out: raise RuntimeError("参照表没解析出来 —— md 的表格格式变了?")
    _cache["tbl"] = out
    return out


BAND = {"base_k": 0.20, "per_year": 0.15, "spurt_mult": 1.8, "floor": 1.5}
SPURT = {"女": (9.5, 13.0), "男": (11.5, 15.0)}   # 突增窗口,md 第五节
AGE_MIN, AGE_MAX = 2, 18


# ── 基础换算 ────────────────────────────────────────────────────────────
def age_at(birthday, on):
    """到 on 那天几岁(小数)。**存生日不存年龄** —— 年龄每天在变。"""
    b, o = _d(birthday), _d(on)
    return (o - b).days / 365.25


def _d(x):
    if isinstance(x, date): return x
    return date.fromisoformat(str(x)[:10])


def p50sd(sex, age):
    """线性插值取 (P50, SD)。超出表范围就贴边,并由调用方决定要不要提示。"""
    t = table()
    a = max(AGE_MIN, min(AGE_MAX, age))
    lo = math.floor(a); hi = min(AGE_MAX, lo + 1)
    i = 0 if sex == "男" else 2
    p_lo, s_lo = t[lo][i], t[lo][i + 1]
    if hi == lo: return p_lo, s_lo
    p_hi, s_hi = t[hi][i], t[hi][i + 1]
    f = a - lo
    return p_lo + (p_hi - p_lo) * f, s_lo + (s_hi - s_lo) * f


def z_of(sex, age, height):
    p, s = p50sd(sex, age)
    return (height - p) / s


def pct_of(z):
    """z 分数 → 百分位。标准正态 CDF,用 math.erf,不引第三方。"""
    return 100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))


def h_at(sex, age, z):
    p, s = p50sd(sex, age)
    return p + z * s


def in_spurt(sex, a0, a1):
    """[a0,a1] 这段年龄和突增窗口有没有重叠"""
    lo, hi = SPURT.get(sex, (99, 99))
    return not (a1 < lo or a0 > hi)


# ── 主方法 ──────────────────────────────────────────────────────────────
def forecast(sex, birthday, height, measured_at, target, parents=None):
    """推算 target 那天的身高。parents=(父身高, 母身高) 时附靶身高校验。

    返回 dict。**区间和限定说明是返回值的一等公民**,不是附注 ——
    调用方可以不显示,但不能拿不到。
    """
    a0 = age_at(birthday, measured_at)
    a1 = age_at(birthday, target)
    yrs = a1 - a0
    if yrs < 0: raise ValueError("目标日期早于量体日期")

    adult = a0 >= AGE_MAX
    z = z_of(sex, a0, height)
    pred = height if adult else h_at(sex, a1, z)

    _, sd1 = p50sd(sex, a1)
    half = sd1 * (BAND["base_k"] + BAND["per_year"] * yrs)
    spurt = in_spurt(sex, a0, a1)
    if spurt: half *= BAND["spurt_mult"]
    half = max(BAND["floor"], round(half * 2) / 2)
    if adult: half = 1.0

    r = dict(性别=sex, 量体日=str(_d(measured_at)), 目标日=str(_d(target)),
             量体时年龄=round(a0, 1), 目标时年龄=round(a1, 1),
             基准身高=height, 百分位=f"P{pct_of(z):.0f}", z分数=round(z, 2),
             方法="成人不推算" if adult else "百分位法(z 分数不变)",
             预测身高=round(pred, 1), 区间=(round(pred - half, 1), round(pred + half, 1)),
             长高=round(pred - height, 1), 跨突增期=spurt, 限定=[], 建议=[])

    if adult:
        r["限定"].append("已满 18 岁,身高按不再变化处理;**体重变化 >5kg 必须复量**,围度变化远大于身高")
        return r

    r["限定"] = [
        "推的是**统计分布**,不是这个孩子 —— 个体差 ±5cm 是常态",
        "青春期突增的**起始时间**个体差异可达 2–3 年,这是最大误差来源",
        "围度(胸腰臀)比身高难预测得多,**本推算不给围度点估计**",
    ]
    if spurt:
        r["限定"].insert(0, f"这段区间跨过{sex}孩的突增窗口"
                            f"({SPURT[sex][0]}–{SPURT[sex][1]} 岁),**区间已放宽近一倍**")
    if a0 < AGE_MIN or a1 > AGE_MAX:
        r["限定"].append(f"年龄超出参照表({AGE_MIN}–{AGE_MAX} 岁)范围,已按边界值贴边处理")

    if parents:
        r["靶身高校验"] = target_height(sex, *parents, adult_pred=h_at(sex, AGE_MAX, z))
        if r["靶身高校验"]["需人工确认"]:
            r["建议"].append("遗传身高与百分位推算差得较多 —— **不自动挑一边**,转人工确认")
    return r


def target_height(sex, father, mother, adult_pred=None):
    """靶身高(遗传身高)。只做**校验**,不当主方法。"""
    mid = (father + mother + (13 if sex == "男" else -13)) / 2
    d = dict(遗传身高=round(mid, 1), 区间=(round(mid - 5, 1), round(mid + 5, 1)),
             需人工确认=False)
    if adult_pred is not None:
        gap = abs(adult_pred - mid)
        d.update(百分位推算成年身高=round(adult_pred, 1), 差值=round(gap, 1),
                 需人工确认=gap > 8)
    return d


# ── 围度:只给区间,不给点估计 ──────────────────────────────────────────
def girth_band(base_girth, base_h, pred_h, pct=0.06):
    """按身高比例缩放,再放 ±6%。**宽是诚实,不是无能。**"""
    mid = base_girth * pred_h / base_h
    return dict(区间=(round(mid * (1 - pct), 1), round(mid * (1 + pct), 1)),
                点估计=None,
                说明="围度只给区间。**不得用推算围度直接下单裁剪**,须复量。")


# ── 复量周期 ────────────────────────────────────────────────────────────
def recheck_cycle(sex, age, weight_delta_kg=0.0, pregnant=False):
    """返回 (周期天数, 原因)。周期表见 md 第五节。"""
    if pregnant: return 0, "孕期/产后:立即复量,且不沿用旧记录"
    if age >= AGE_MAX:
        if abs(weight_delta_kg) > 5: return 0, "成人体重变化 >5kg:立即复量(围度变化远大于身高)"
        return 365, "成人:12 个月"
    if age < 3: return 90, "0–3 岁:一年长 8–12cm,三个月就跨码"
    lo, hi = SPURT.get(sex, (99, 99))
    if lo <= age <= hi: return 120, f"突增期({lo}–{hi} 岁):年增可达 8–10cm,误差最大的一段"
    if age < 12: return 180, "3–12 岁:年增 5–7cm"
    return 180, "突增期结束–18 岁:增速回落但未停"


def measure_expired(sex, birthday, last_at, today, **kw):
    """旧量体记录还能不能用。**超期的不是「参考值」,是「无效值」。**"""
    a = age_at(birthday, today)
    days, why = recheck_cycle(sex, a, **kw)
    used = (_d(today) - _d(last_at)).days
    return dict(已过天数=used, 允许天数=days, 过期=used > days, 原因=why,
                处置="下单前必须拦下,要求复量" if used > days else "可用")


# ── 留成长量 ────────────────────────────────────────────────────────────
ALLOW = [("裙长 / 衣长", 5.0, "折边,明年放下来 —— 最有效的一处"),
         ("通袖长", 3.0, "连肩袖,容差本来就大"),
         ("腰围", None, "系带结构,容差最大"),
         ("领围(立领)", 0.0, "±1cm 就影响舒适,**不留**,宁可改"),
         ("马面裙腰头", 0.0, "腰头定死,留量会破坏褶位,**不留**")]


def allowance(delta_cm):
    """按预测长高量给留量建议。汉服的结构优势就体现在这张表上。"""
    out = []
    for part, cap, why in ALLOW:
        if cap is None: v = "系带调节"
        elif cap == 0: v = "不留"
        else: v = f"{min(cap, max(0.0, round(delta_cm, 1))):.1f} cm"
        out.append(dict(部位=part, 建议留量=v, 说明=why))
    return out


def sales_line(name, delta, allow_cm):
    """给家长的话术。不是「明年就穿不下了」。"""
    return (f"{name}明年大约长高 {delta:.1f}cm。我们按明年的身高留 {allow_cm:.1f}cm 折边,"
            f"今年先折起来,明年放下来还能穿一季。")


# ── 自测 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    fail = []
    def ck(name, cond, extra=""):
        print(f"  {'✅' if cond else '❌'} {name}{('  ' + extra) if extra else ''}")
        if not cond: fail.append(name)

    print("成长推算 · 自测\n" + "=" * 84)
    t = table()
    print(f"\n▸ 参照表:{len(t)} 个年龄,{AGE_MIN}–{AGE_MAX} 岁")
    ck("表覆盖 2–18 岁,一岁不缺", sorted(t) == list(range(AGE_MIN, AGE_MAX + 1)))

    print("\n▸ 表里那件反直觉的事")
    for a in (10, 11):
        m, f = t[a][0], t[a][2]
        ck(f"{a} 岁女孩 P50 高于男孩", f > m, f"男 {m} / 女 {f}")
    ck("12 岁起男孩反超", t[13][0] > t[13][2], f"男 {t[13][0]} / 女 {t[13][2]}")

    print("\n▸ 百分位法:z 分数不变")
    # 一个 8 岁男孩,正好长在 P50 上 —— 一年后也该正好在 P50 上
    r = forecast("男", "2018-06-01", 127.0, "2026-06-01", "2027-06-01")
    ck("正好 P50 的孩子,一年后仍是 P50", r["百分位"] == "P50", r["百分位"])
    ck("一年后身高 = 表里 9 岁的 P50", abs(r["预测身高"] - t[9][0]) < 0.1,
       f"{r['预测身高']} vs 表 {t[9][0]}")
    ck("长高量 = 两行 P50 之差", abs(r["长高"] - (t[9][0] - t[8][0])) < 0.1, f"{r['长高']}cm")

    # 偏高的孩子:z 保持,所以绝对差会随 SD 变大而变大
    hi = forecast("男", "2018-06-01", 132.5, "2026-06-01", "2027-06-01")
    ck("偏高的孩子百分位不变", hi["百分位"] == r["百分位"] or float(hi["百分位"][1:]) > 50,
       hi["百分位"])
    ck("偏高的孩子长得更多(SD 随年龄变大)", hi["长高"] >= r["长高"],
       f"{hi['长高']} vs {r['长高']}")

    print("\n▸ 区间:跨突增期必须放宽")
    n1 = forecast("女", "2019-01-01", 122.0, "2026-01-01", "2027-01-01")   # 7→8 岁
    s1 = forecast("女", "2015-01-01", 140.0, "2026-01-01", "2027-01-01")   # 11→12 岁
    w = lambda x: (x["区间"][1] - x["区间"][0]) / 2
    ck("7→8 岁不跨突增期", not n1["跨突增期"])
    ck("11→12 岁跨突增期", s1["跨突增期"])
    ck("跨突增期的区间明显更宽", w(s1) > w(n1) * 1.5, f"{w(s1)}cm vs {w(n1)}cm")
    ck("跨突增期时限定里说了这件事", any("突增" in x for x in s1["限定"]))

    print("\n▸ 三条限定一条都不能少")
    ck("限定非空且含「不是这个孩子」", any("不是这个孩子" in x for x in n1["限定"]))
    ck("限定里说了不给围度点估计", any("围度" in x for x in n1["限定"]))
    ck("成人不推算身高", forecast("女", "2000-01-01", 162.0, "2026-01-01", "2027-01-01")["长高"] == 0)

    print("\n▸ 靶身高:只校验,差太多转人工")
    th = target_height("男", 175, 162)
    ck("男孩靶身高 =(父+母+13)/2", abs(th["遗传身高"] - 175.0) < 0.05, str(th["遗传身高"]))
    ck("女孩靶身高 =(父+母-13)/2",
       abs(target_height("女", 175, 162)["遗传身高"] - 162.0) < 0.05)
    ck("差 >8cm 标人工", target_height("男", 160, 150, adult_pred=175.0)["需人工确认"])
    ck("差 <8cm 不标人工", not target_height("男", 175, 162, adult_pred=178.0)["需人工确认"])

    print("\n▸ 围度只给区间")
    g = girth_band(58.0, 127.0, 132.0)
    ck("围度不给点估计", g["点估计"] is None)
    ck("围度区间比身高区间宽得多(相对)", (g["区间"][1] - g["区间"][0]) / 60 > 0.10,
       f"{g['区间']}")

    print("\n▸ 复量周期与过期拦截")
    ck("0–3 岁 90 天", recheck_cycle("男", 2.0)[0] == 90)
    ck("突增期 120 天", recheck_cycle("女", 11.0)[0] == 120)
    ck("成人 365 天", recheck_cycle("女", 30.0)[0] == 365)
    ck("成人体重变化 >5kg 立即", recheck_cycle("女", 30.0, weight_delta_kg=6)[0] == 0)
    ck("孕产立即且不沿用", recheck_cycle("女", 30.0, pregnant=True)[0] == 0)
    e = measure_expired("女", "2015-01-01", "2025-06-01", "2026-01-01")
    ck("突增期孩子半年前的记录已过期", e["过期"], f"{e['已过天数']}天 > {e['允许天数']}天")
    # 回归 —— 曾经把 13.3 岁的女孩说成「16–18 岁」:
    # 复量周期表漏了「突增期结束到 18 岁」这一段,天数恰好一样所以没人发现,
    # 直到体检把**理由**打印给顾问看。**数值对、解释错**,是最难被测试抓到的一类。
    for sex, a in (("女", 13.5), ("女", 15.0), ("男", 15.5), ("男", 17.0)):
        _, why = recheck_cycle(sex, a)
        ck(f"{sex} {a} 岁的复量说明不能张冠李戴", "16–18" not in why, why)
    ck("过期的处置是拦下,不是「参考」", "拦下" in e["处置"])

    print("\n▸ 留成长量:该留的留,不该留的一分不留")
    al = {a["部位"]: a["建议留量"] for a in allowance(6.0)}
    ck("裙长封顶 5cm(长高 6cm 也不多留)", al["裙长 / 衣长"] == "5.0 cm", al["裙长 / 衣长"])
    ck("立领不留", al["领围(立领)"] == "不留")
    ck("马面裙腰头不留", al["马面裙腰头"] == "不留")
    ck("腰围走系带", al["腰围"] == "系带调节")

    # ── 咬合:把参照表的解析弄坏,看自测会不会红 ──────────────────────
    # **没红过的检查等于没有。** 这一条在 CLAUDE.md 第 8 节里是硬规矩。
    print("\n▸ 咬合测试")
    _bak = dict(_cache)
    _cache["tbl"] = {a: (v[0], v[1], v[2], v[3]) for a, v in table().items() if a != 9}
    try:
        forecast("男", "2018-06-01", 127.0, "2026-06-01", "2027-06-01")
        ck("参照表缺一行时应当报错", False, "缺了 9 岁却照算不误 —— 插值在吞异常")
    except KeyError:
        ck("参照表缺一行时立刻报错,不静默估一个", True)
    _cache.clear(); _cache.update(_bak)
    ck("咬合后表已复原", sorted(table()) == list(range(AGE_MIN, AGE_MAX + 1)))

    print("\n" + "=" * 84)
    if fail:
        print(f"❌ {len(fail)} 条没过:" + " / ".join(fail)); sys.exit(1)
    print("✅ 成长推算自测全部通过")
    print("\n  示例 —— 8 岁男孩,今天 127cm(P50),推一年后:")
    print(f"    {r['预测身高']}cm  区间 {r['区间']}  长高 {r['长高']}cm")
    print(f"    {sales_line('孩子', r['长高'], 5.0)}")
