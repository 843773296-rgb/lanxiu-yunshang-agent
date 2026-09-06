#!/usr/bin/env python3
"""RFM 评分 · **性质检查**(不是逐例真值)。

## 为什么这里不逐例标真值

八档是**绝对**判定 —— 第 90 天就是活跃,标一次永远成立,所以 `member_check.py`
逐条对 14 个边界标注。

RFM 五分位是**相对**的 —— 分数取决于整个客户群的分布,数据一变分数就变。
逐例标注第二天就过期,而且过期时不会报错,只会开始误报。
**别把两者混为一谈:绝对判定逐例标,相对指标验性质。**

验的四条性质,每一条都对应一种运营会当场看穿的错:

  ① 同值同分 —— 两个数据一模一样的客户分数不同,运营只会得出「这系统不准」,而他是对的
  ② 单调不反 —— 越久没来 R 分越高,那是把该联系的排到了最后
  ③ 分布不塌 —— 全挤在一档等于没打分,而列表看起来完全正常(和 E2 同族)
  ④ 排序确定 —— 今天的名单和明天不一样、数据却一个字没变,没人会再信它
"""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge"))
import rfm as _rfm, lifecycle as _lc

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
ALL = [dict(r) for r in c.execute(
    "SELECT id,name,lifecycle,idle_days,orders_12m,amount_12m FROM customer")]

bad = []
def rule(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    for r in rows[:5]: print(f"        · {r}")
    if rows: bad.append((no, why, len(rows)))

print(f"RFM 性质检查 · {len(ALL)} 位客户")
print("=" * 92)
scored = _rfm.score(ALL)

# ① 同值同分
DIM = [("R", "idle_days"), ("F", "orders_12m"), ("M", "amount_12m")]
p1 = []
for k, col in DIM:
    seen = {}
    for r in scored:
        v = r.get(col)
        if v in seen and seen[v] != r[k]:
            p1.append(f"{k}:{col}={v} 既得 {seen[v]} 分又得 {r[k]} 分")
        seen[v] = r[k]
rule("F1", "同值必须同分", p1,
     "两个数据一模一样的客户分数不同,运营只会得出「这系统不准」—— 而他是对的")
# ⚠️ **F1 现在是「靠结构成立」,不是「靠检查守着」。**
# rfm._score 返回的是 {原值: 分数} 的字典,按值查表,同值必然同分 ——
# 想破也破不了。咬合时试过「按人头分桶」,没红:字典键去重把它抵消了。
# 真能破它的是把打分改成**按行**算(rs.get(...) - i % 2),那才红。
#
# 记下来是因为「靠结构」和「靠检查」的可靠性不一样:
# 结构成立的那条,只要有人把打分改成逐行计算就会失守,而 F1 那时才开始起作用。
# 现在它是**回归网**,不是当下的防线 —— 边界审计里这两类要分开记。

# ② 单调
p2 = []
for k, col in DIM:
    pairs = sorted({(r[col], r[k]) for r in scored})
    smaller_better = (k == "R")
    for (v1, s1), (v2, s2) in zip(pairs, pairs[1:]):
        if smaller_better and s2 > s1: p2.append(f"{k}:{col} {v1}→{v2} 分数反而涨({s1}→{s2})")
        if not smaller_better and s2 < s1: p2.append(f"{k}:{col} {v1}→{v2} 分数反而降({s1}→{s2})")
rule("F2", "单调不能反", p2,
     "越久没来 R 分越高,等于把最该联系的人排到了最后 —— 而列表看起来完全正常")

# ③ 分布不塌
p3 = [f"{k} 只用到 {len({r[k] for r in scored})} 档" for k, _ in DIM
      if len({r[k] for r in scored}) < 3]
rule("F3", "分数分布不许塌(每维至少用到 3 档)", p3,
     "全挤在一档等于没打分,而名单看起来一切正常 —— 和 E2「两个维度不得完全相关」同族")

# ④ 排序确定
p4 = []
a = [r["id"] for r in _rfm.score(ALL)]
b = [r["id"] for r in _rfm.score(list(reversed(ALL)))]
if a != b: p4.append(f"输入顺序变了,输出次序就变(第 {next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)+1} 位起不同)")
rule("F4", "排序必须确定(与输入顺序无关)", p4,
     "今天的名单和明天不一样、数据却一个字没变,没人会再信这个排序")

# ⑤ 每一档都排得出来(接口层不会因为某档人少而炸)
p5 = []
for lc in _lc.PRIORITY:
    grp = [r for r in ALL if r["lifecycle"] == lc]
    if not grp: continue
    try:
        out = _rfm.score(grp)
        if len(out) != len(grp): p5.append(f"{lc}:进 {len(grp)} 人出 {len(out)} 人")
    except Exception as e: p5.append(f"{lc}:排序抛异常 {type(e).__name__}")
rule("F5", "每个档位都排得出来(含只有一两个人的档)", p5,
     "分桶在样本极少时最容易出边界错,而那几档恰恰是运营最常点开的")

print("\n" + "=" * 92)
if bad:
    print(f"❌ {len(bad)} 条性质没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    sys.exit(1)
print(f"✅ 五条性质全部守住 —— 相对指标验的是性质,不是逐例真值")
