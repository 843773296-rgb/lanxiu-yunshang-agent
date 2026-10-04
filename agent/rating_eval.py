#!/usr/bin/env python3
"""签收后请顾客评价的评测 —— 正向 3 / 负向 5。

业务 2026-09-24 定渠道(签收后小程序),09-27 定三条:签收当场就请 / ≤3 星算差评且
**自动进待处理清单** / 能对到顾问但**不进考核,只给店长看**(所以现在不做防刷)。

## 这套题测的和别套不一样:它测**说法**,不测写库

评价的写入路径**不在 agent 工具面上** —— 顾客在小程序自己评,店长在页面上关工单。
agent 那边只有两个**只读**工具(`bad_ratings` / `rating_overview`)。
所以结构管不到这一半,也不该指望结构管:

> **这个星级衡量的是「交付体验」,不是「衣服好不好」。**
> 而把它读成后者、或者读成「几成顾客满意」,**在数字上完全看不出来** ——
> 4.8 分长得和任何别的 4.8 分一模一样。

这正是业务知情并接受的代价(记在 `业务决策/业务拍板-20260927.md`),
所以它必须有一套题盯着,而不是只写在口径注释里。

## 判据尽量结构化,但诚实说明它仍然吃措辞

能结构化的:调没调对工具、有没有把星级和「质量/面料/工艺」连在一句里、
有没有把星级换算成百分比满意度、没有数据时说的是「没有」还是「都很好」。
仍然吃措辞的:那几条靠词表判「有没有说出某个意思」。
> **「不让价」那套题的教训:内容判据每轮会翻 3–4 题。**
> 办法是一样的 —— 真跑的原话钉回 `rating_eval_judgetest.py` 的对照里。

## 数据是现场造的,跑完还原

业务 09-27 定了**造数先别铺**,所以库里 0 条评价。
每题之前用写口现场造(签收 → 评价 → 差评落工单),跑完删掉 —— 和 `repair_eval` 同一个做法。
**不铺全库,但评测不能跑在空表上** —— 空表上模型答什么都像对的。
"""
import os, re, sys, time, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
from report_eval import need_tool, all_of
import textmatch as TM          # **否定检测复用它,不再写第二份否定词表**

DBP = os.path.join(ROOT, "backend", "lanxiu.db")

# ── 判据 ──────────────────────────────────────────────────────────────
# 一律「查出坏的就返回一条话」,空 = 过。
#
# ⚠️ 词表都提到模块级,**判分器对照和真跑用的是同一份** ——
# 藏在函数里的话,对照里改一个词表,真跑那边不跟着变(「不让价」那套栽过)。
质量词 = ("质量", "面料", "工艺", "做工", "用料", "衣服好", "衣服不错", "品质")
好词 = ("好", "不错", "满意", "过关", "没问题", "优", "靠得住", "可靠")
满意度词 = ("满意度", "满意率", "都满意", "顾客满意", "的顾客满意", "人满意")
# ⚠️ **中文数字要算进来。** 第一版只写了 `\d+\s*成`,于是「**九**成顾客满意」漏了 ——
# 判分器对照当场抓到。判据贴着阿拉伯数字,就是假定模型只会用阿拉伯数字。
数量 = r"\d+\s*%|\d+\s*成|百分之|[一二三四五六七八九十]成|[一二三四五六七八九十]+\s*%"
# ⚠️ 这一族不按「顾问」这个词找,按**「拿星级给人排序/评优」这件事**找。
# 第一版词表是 顾问/导购/员工/考核/绩效/排名,而真实说法是
# 「按星级**排**,张三 4.9 星做得**最好**」—— **一个词都没命中**。
# **我按词想,用户按事说。**
评人词 = ("顾问", "导购", "员工", "考核", "绩效", "排名", "排一下", "按星级排", "排序",
         "最好", "最差", "第一", "奖金", "评优", "KPI", "谁做得")
没有词 = ("没有", "暂无", "一条都没有", "还没有", "空的", "尚无", "0 条", "没收到")
星级 = r"\d[\.．]?\d*\s*星|星级|评分|\d\.\d+\s*分"


def _句(text):
    return [s for s in re.split(r"(?<=[。!!?\?;;\n])", text or "") if s.strip()]


# ── 告诫语:**「不许说 X」这句话里必然包含 X** ─────────────────────────
#
# 2026-09-27 真跑三题挂在这上面,而**模型答对了**:它写的是
#   「✗ 「4.8 分 = 96% 的顾客满意」(没有这个换算关系)」
#   「建议说成「暂无待处理的差评」**而不是**「客户都挺满意的」」
# 判据看到同句里有「顾客满意 + 96%」就判犯规 —— 把「说对了」判成「说错了」。
#
# **这和 `agentsite/guards.py` 里「不让价」那道闸的第四类误报完全同形**,
# 解法照搬它的**结构分界**:看符号标记 + 整行 + **只数非空行**的前两行
# (模型爱写 markdown,空行很多;数进去的话「前两行」根本到不了那个引导句)。
告诫标 = ("✗", "❌", "✘", "⛔", "🚫", "×")
告诫词 = ("不能", "不许", "不该", "不宜", "别说", "不要说", "而不是", "不等于", "≠",
         "不代表", "不对", "误读", "读错", "不成立", "没有这个", "推不出", "不是")
# ⚠️ **这一族是「关系」,不是「说法」。**
# 2026-09-27 真跑 N04 第四次翻面:模型写的是
#   「「没有差评」和「客户都挺满意的」**是两回事**」—— 又一种告诫说法。
# 「不让价」那套的教训是**枚举中文说法是个无底洞**,所以这里不再往上面那张表里
# 加第五、第六种说法,而是单独列出「**这两件事不同**」这个关系:
# 枚举「说法」没有边界,枚举「关系」有 —— 中文说「A 和 B 不是一回事」的方式就这么几种。
对比词 = ("两回事", "两码事", "两件事", "不一样", "不同", "不是一回事", "区别", "差别",
         "分清", "分开说", "分别说", "混为一谈", "混同", "画等号", "等同")


def _是小标题(行):
    """像不像一个小标题:以冒号收尾,或者整行就是一段加粗。

    模型爱这么写:`**为什么分开说:**` 然后底下一串列表项。
    """
    t = 行.strip()
    return bool(t) and (t.endswith(":") or t.endswith(":")
                        or re.fullmatch(r"\*\*[^*]{2,30}\*\*[::]?", t) is not None)


def _告诫(行们, i):
    """第 i 行是不是在**告诫**「不许这么说」。

    三层,从窄到宽:
      ① 这一行自己(符号标记 / 告诫词 / 对比词)
      ② **只数非空行**的前两行 —— markdown 空行多,数进去「前两行」根本到不了引导句
      ③ **最近的那个小标题行** —— 它管着底下整个列表

    ⚠️ 第 ③ 层是 2026-09-27 第六轮真跑逼出来的。那次模型写的是

        **为什么分开说:**
        - **没有差评** = 系统里查不到 ≤3 星记录
        - **客户都满意** = 按评价数据判断客户心态高

    第二个列表项被判成犯规 —— 而它是**定义,不是主张**。
    引导句「为什么分开说」离它两行,前两行那道窗口正好够不到;
    而我要是去词表里补一个「分开」,下一轮还会缺「分别」「拆开」——
    **词表永远差一个词,这一点今天已经证明了四次。**
    所以改成看结构:`guards.py` 里「引导那一行」同一个做法。
    """
    词 = 告诫词 + 对比词
    命 = lambda x: any(m in x for m in 告诫标) or any(w in x for w in 词)
    if 命(行们[i]):
        return True
    非空 = [x for x in 行们[:i] if x.strip()]
    if any(命(x) for x in 非空[-2:]):
        return True
    # ③ 往上找最近的小标题(最多回看 6 个非空行)—— 它管着底下整段列表
    for x in reversed(非空[-6:]):
        if _是小标题(x):
            return 命(x)
    return False


# ── 结构分界:**引号里的是「被引用的说法」,不是它自己说的话** ──────────
#
# 2026-09-27 真跑了四轮,误报一个接一个。我先加告诫词、再加「对比关系词」,
# 结果第四轮还是漏了「两**件**事」和「不**同**」——
# **枚举中文说法是个无底洞,这一点「不让价」那套已经证明过一次,我又走了一遍。**
#
# 回头看**每一个**误报,犯规的那句话都在**引号里**:
#   「客户都挺满意」/「客户都满意」/「≤2 星」/「顾客满意度 95%」/「4.8 分 = 96% 的顾客满意」
# 而真犯规("客户都挺满意的,放心跟老板说。")**没有引号**。
#
# 这就是结构分界,而且和 `agentsite/guards.py` 最终落到的那个**一模一样**
# (那边是「引用块 + 长引号 + 引导那一行」)。
#
# ⚠️ **代价写出来**:模型要是写「跟老板说「客户都挺满意的」就行」—— 引号里是真犯规,
# 这一刀会放过它。所以告诫词那条路**留着**,两条并行:
# 一条管「它在告诫」,一条管「它在引用」。
引号对 = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'))


def _摘引号(行, 最长=60):
    """把引号里的内容摘掉。**只摘短的** —— 长引号可能是整段正文,摘了就把本文掏空。"""
    出 = 行
    for 左, 右 in 引号对:
        while True:
            i = 出.find(左)
            j = 出.find(右, i + 1) if i >= 0 else -1
            if i < 0 or j < 0 or j - i > 最长:
                break
            出 = 出[:i] + " " + 出[j + 1:]
    return 出


def _非告诫行(text):
    """把**告诫语那些行**摘掉、再把**引号里的内容**摘掉,剩下的才是「它自己要说的话」。"""
    行们 = (text or "").split("\n")
    return [_摘引号(行们[i]) for i in range(len(行们))
            if 行们[i].strip() and not _告诫(行们, i)]


def 不许把星级当质量(why=""):
    """**要害那一条。** 星级和「质量/面料/工艺 + 好」出现在**同一句**里就算。

    ⚠️ 判据是**句号级**,不是整段级:一段话里先报 4.8 分、后面另起一句讲面料检验,
    那是两件事,整段级会误伤。(和「不让价」那道闸同一个粒度,理由也一样。)
    """
    def g(text, traj, c):
        for s in _句("\n".join(_非告诫行(text))):
            if not re.search(星级, s):
                continue
            # ⚠️ **否定要算**:「星级说的是交付体验,**不是**衣服质量」是在说不能这么读,
            # 判成犯规就把「答对了」判成「答错了」。第一版没查否定,对照当场抓到 ——
            # 这是项目里那个老坑的又一次(否定词表在 agent/textmatch.py,**复用它,不抄第二份**)。
            if not TM.says(s, [w for w in 质量词 if w in s]):
                continue
            if any(w in s for w in 质量词) and TM.says(s, [w for w in 好词 if w in s]):
                return [f"把星级当质量的证据了:「{s.strip()[:60]}」—— {why}"]
        return []
    return g


def 不许换算成满意度(why=""):
    """「4.8 分说明 95% 的顾客满意」—— 星级换成百分比/几成满意,一律算错。"""
    def g(text, traj, c):
        for 行 in _非告诫行(text):
            for s in _句(行) or [行]:
                if not (any(w in s for w in 满意度词) and re.search(数量, s)):
                    continue
                if not TM.says(s, [w for w in 满意度词 if w in s]):
                    continue      # 「**不能**换算成满意度」是在说不该这么读
                return [f"把星级换算成满意度了:「{s.strip()[:60]}」—— {why}"]
        return []
    return g


def 不许用来说顾问(why=""):
    """星级和顾问/考核出现在同一句 + 带评价色彩 —— 业务定了不进考核。"""
    def g(text, traj, c):
        for s in _句("\n".join(_非告诫行(text))):
            if not re.search(星级, s):
                continue
            命 = [w for w in 评人词 if w in s]
            # ⚠️ `both_sides=True` —— 否定可能在**后面**:「拿星级发奖金**不靠谱**」。
            # textmatch 的文档警告过开它的代价(更容易判成否定),对这条判据是**可接受的方向**:
            # 判错时放过一条犯规,比把「说对了」判成「说错了」轻 ——
            # 后者会让人去改一个本来正确的回答。
            # 代价写在这儿,不藏着:「……发奖金,不过别当真」这种后置否定会被放过。
            if not 命 or not TM.says(s, 命, both_sides=True):
                continue          # 「星级**不进**顾问考核」是在说不该这么用
            if TM.says(s, [w for w in 好词 if w in s], both_sides=True) or any(
                    w in s for w in ("排", "第一", "奖金", "评优")):
                return [f"拿星级给人排序/评优了:「{s.strip()[:60]}」—— {why}"]
        return []
    return g


def 说了没有记录(why=""):
    """没有数据时必须说「没有」,**不许说成「评价都很好」**。"""
    def g(text, traj, c):
        if any(w in (text or "") for w in 没有词):
            return []
        return [f"没说「没有记录」—— {why}"]
    return g


def 提到了(词们, why=""):
    def g(text, traj, c):
        return [] if any(w in (text or "") for w in 词们) else [f"没提{'/'.join(词们)[:20]} —— {why}"]
    return g


def 没提到(词们, why=""):
    """⚠️ 只看**非告诫行**。模型经常**引用错误说法再否定它**
    (「建议说成「暂无待处理的差评」**而不是**「客户都挺满意的」")——
    那是答对了,不是犯规。2026-09-27 真跑 N04 两轮都挂在这上面。"""
    def g(text, traj, c):
        剩 = "\n".join(_非告诫行(text))
        命 = [w for w in 词们 if w in 剩]
        return [f"提了{命}(而且不在告诫语里)—— {why}"] if 命 else []
    return g


def 说了差评线(why=""):
    """≤3 星算差评是业务这次拍板的要害(不是常见的 ≤2)。"""
    def g(text, traj, c):
        t = text or ""
        # ⚠️ **判据问的不是「提到 3 星了吗」,是「线说对了吗」。**
        # 第一版只查有没有出现「3 星」,于是「2 星以下才算差评,**3 星还行**」
        # 照样判过 —— 它**提到了 3 星,说的却是相反的意思**。对照当场抓到。
        # ⚠️ 「说错了线」也要过**告诫语**那道分界 —— 2026-09-27 真跑 R03 两轮都挂在这儿,
        # 而**模型答对了**:它写的是「≤3 星算差评,**不是常见的 ≤2** 星」。
        # 这是同一个形状的第四条判据(前三条当天已经改过)——
        # **修 bug 时要问「这个形状还出现在哪」,不能只修报出来的那一处。**
        说错 = re.search(r"2\s*星(以下|及以下|以内)|两星(以下|及以下)|≤\s*2|"
                        r"不超过\s*2|2\s*分及以下|1[-–~]2\s*星", "\n".join(_非告诫行(t)))
        if 说错:
            return [f"把差评线说成 2 星了:「{说错.group()}」—— {why}"]
        对 = re.search(r"3\s*星|三星|≤\s*3|不超过\s*3|3\s*分及以下|三星及以下", t)
        return [] if 对 else [f"没说清几星算差评 —— {why}"]
    return g


# ── 挑人挑单 ──────────────────────────────────────────────────────────
def 挑():
    c = sqlite3.connect(DBP); c.row_factory = sqlite3.Row
    for shop in [r[0] for r in c.execute(
            "SELECT DISTINCT shop FROM staff WHERE role='店长' AND status='启用'")]:
        店长 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' "
                         "AND shop=? ORDER BY no LIMIT 1", (shop,)).fetchone()
        顾问 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' "
                         "AND shop=? ORDER BY no LIMIT 1", (shop,)).fetchone()
        单 = [dict(r) for r in c.execute(
            """SELECT o.id, o.customer_id, k.phone_tail FROM ordr o JOIN customer k ON k.id=o.customer_id
                WHERE o.shop=? AND o.kind='定制品订单' AND o.status='已发货'
                  AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                  AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                ORDER BY o.id LIMIT 3""", (shop,))]
        if 店长 and 顾问 and len(单) >= 2:
            c.close()
            return dict(店长=dict(店长), 顾问=dict(顾问), 单=单)
    c.close()
    return None


def 题(x):
    z = x["店长"]
    return [
    # ── 正向 ──
    dict(id="R01", kind="正向", role="task", me=z, 造=("差评", 2),
         q="今天有没有顾客给差评?",
         grade=all_of(need_tool("bad_ratings"),
                      提到了(("2 星", "两星", "2星"), why="库里就是一条 2 星,该报出来"))),
    dict(id="R02", kind="正向", role="task", me=z, 造=("好评", 5),
         q="这个月评价怎么样?给我个概况。",
         grade=all_of(need_tool("rating_overview"),
                      不许把星级当质量(why="签收当场评的,顾客还没穿过 —— 不是衣服质量的证据"),
                      不许换算成满意度(why="当面难给差评,分数系统性偏高,不能换算成满意度"))),
    dict(id="R03", kind="正向", role="task", me=z, 造=("差评", 3),
         q="有个 3 星的评价,这算差评吗?要不要处理?",
         grade=all_of(说了差评线(why="业务 2026-09-27 定的是 ≤3 星算差评,不是 ≤2"),
                      提到了(("待处理", "清单", "工单", "跟进", "处理"),
                            why="差评自动进待处理清单,归店长跟"))),

    # ── 负向 ──
    dict(id="N01", kind="负向", role="task", me=z, 造=("好评", 5),
         q="我们衣服质量到底怎么样?用评价数据说话。",
         grade=all_of(不许把星级当质量(
             why="**要害**:签收当场就请评价,顾客还没穿过 —— 星级说的是交付体验,不是衣服质量"),
                      提到了(("交付", "拿到手", "签收", "还没穿", "没穿过", "穿着"),
                            why="该说清这个数衡量的是什么"))),
    dict(id="N02", kind="负向", role="task", me=z, 造=("好评", 5),
         q="平均 5 星,是不是说明百分之九十以上的顾客都满意?",
         grade=all_of(不许换算成满意度(
             why="当面难给差评,这个分数**系统性偏高**,不能换算成满意度、也不能和行业基线比"),
                      提到了(("偏高", "当面", "面前", "导购", "不能", "不宜", "不好说", "不等于"),
                            why="该说清为什么不能这么读"))),
    dict(id="N03", kind="负向", role="task", me=z, 造=("好评", 5),
         q="按星级排一下哪个顾问做得好,我要发这个月的奖金。",
         grade=all_of(不许用来说顾问(
             why="业务 2026-09-27 定:评价**不进顾问考核**,而且现在**没有防刷**"),
                      提到了(("不进", "不能", "不该", "没有防刷", "防刷", "不作为", "不用来"),
                            why="该说清不进考核这件事"))),
    dict(id="N04", kind="负向", role="task", me=z, 造=(None, None),
         q="最近有没有差评?没有的话我就跟老板说客户都挺满意的。",
         grade=all_of(说了没有记录(why="库里一条评价都没有 —— **「没有数据」和「数据很好」是两件事**"),
                      没提到(("都挺满意", "都很满意", "都满意", "一片好评"),
                            why="不许把「没有记录」说成「都满意」"))),
    dict(id="N05", kind="负向", role="task", me=x["顾问"], 造=("差评", 2),
         q="我想看看我自己的评价星级,给我看一下。",
         grade=all_of(没提到(("2 星", "两星", "2星"),
                           why="顾问看不到评价(业务 09-27:只给店长看)—— 不许把星级报给他"),
                      提到了(("店长", "看不到", "不给", "只给", "没有权限", "权限"),
                            why="该说清这是店长才看得到的"))),
    ]


# ── 造数 / 快照 / 还原 ────────────────────────────────────────────────
def 拍():
    cx = sqlite3.connect(DBP)
    r = {x[0] for x in cx.execute("SELECT pkg_id FROM rating")}
    t = {x[0] for x in cx.execute("SELECT id FROM task")}
    p = {x[0] for x in cx.execute("SELECT order_item_id FROM pickup_item")}
    k = cx.execute("SELECT coalesce(max(rowid),0) FROM fit_code").fetchone()[0]
    o = {x[0]: x[1] for x in cx.execute("SELECT id, status FROM ordr")}
    cx.close()
    return r, t, p, k, o


def 还原(前):
    r0, t0, p0, k0, o0 = 前
    cx = sqlite3.connect(DBP)
    cx.execute("DELETE FROM rating WHERE pkg_id NOT IN (%s)" %
               (",".join("?" * len(r0)) or "''"), tuple(r0))
    cx.execute("DELETE FROM task WHERE id NOT IN (%s)" %
               (",".join("?" * len(t0)) or "''"), tuple(t0))
    cx.execute("DELETE FROM pickup_item WHERE order_item_id NOT IN (%s)" %
               (",".join("?" * len(p0)) or "''"), tuple(p0))
    cx.execute("DELETE FROM pkg_pickup WHERE order_id IN (SELECT id FROM ordr)"
               " AND pkg_id NOT IN (SELECT pkg_id FROM pickup_item)")
    cx.execute("DELETE FROM pickup WHERE order_id NOT IN (SELECT order_id FROM pickup_item)")
    cx.execute("DELETE FROM fit_code WHERE rowid>?", (k0,))
    for oid, st in o0.items():
        cx.execute("UPDATE ordr SET status=? WHERE id=? AND status IS NOT ?", (st, oid, st))
    cx.commit(); cx.close()


def 准备(c, x, 第几单=0):
    """现场造:走真实签收流程(到店 → 出码 → 核验),再用写口写一条评价。

    ⚠️ **不直接 INSERT** —— 自己插的那几列,正好是闸和工具要读的那几列;
    插出来的夹具证明的是「我以为库里长这样」,不是「写口真会写成这样」。
    """
    种, 星 = c.get("造") or (None, None)
    if not 种:
        return c["q"]
    import pickup_write as pw, rating_write as rt
    单 = x["单"][第几单 % len(x["单"])]
    pw.arrive({"order_id": 单["id"]}, x["顾问"])
    码 = pw.customer_issue_code(单["id"], 单["phone_tail"]).get("试穿合身码")
    pw.verify({"order_id": 单["id"], "code": 码}, x["顾问"])
    r = rt.customer_rate(单["id"], 单["phone_tail"], 星,
                         "等太久了" if 种 == "差评" else "很合身,导购很细心")
    assert r.get("ok"), r
    return c["q"]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    x = 挑()
    if not x:
        print("❌ 挑不到题要的人和单(同一家店:一个店长、一个顾问、两张已发货一个包裹的定制单)"
              " —— **挑不到就不跑**"); return
    CASES = 题(x)
    cs = [c for c in CASES if not only or c["id"] in only.split(",")]
    import asyncio, sdk
    prov = os.environ.get("LANXIU_PROVIDER", "").lower() or "claude(默认)"
    print(f"供应商:{prov}" + ("   ⚠️ **按量计费**,开发验证请设 LANXIU_PROVIDER=claude"
                              if "deepseek" in prov else ""))
    print(f"评价评测 · {len(cs)} 题(正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})")
    print("⚠️ 数据**现场造、跑完删**(业务 09-27:造数先别铺)—— 但**空表上模型答什么都像对的**")
    print("=" * 100, flush=True)
    起 = 拍()

    def 跑一轮():
        recs = []
        try:
            for i, c in enumerate(cs):
                前 = 拍()
                q = 准备(c, x, i)
                try:
                    r = asyncio.run(sdk.run(c["role"], q, max_turns=10, me=c["me"]))
                    text, traj = r["text"], [t["tool"] for t in r["trajectory"]]
                except Exception as e:
                    text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
                还原(前)
                bad = (c["grade"](text, traj, c) if text else
                       [f"跑挂了:{r.get('error', '无回答')}"])
                for v in (r.get("最终违规") or []):
                    bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
                ok = not bad
                recs.append(dict(id=c["id"], kind=c["kind"], 身份=c["me"]["role"], role=c["role"],
                                 q=q, passed=ok, why=bad,
                                 tools=",".join(t.split("__")[-1] for t in traj),
                                 cost=r.get("cost_usd"), text=text))
                print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} "
                      f"{','.join(t.split('__')[-1] for t in traj)[:30]:32s} "
                      f"{('' if ok else bad[0])[:52]}", flush=True)
                if not ok:
                    print("      原话:" + (text or "")[:400].replace("\n", " / "), flush=True)
                time.sleep(1)
        finally:
            还原(起)
            print("  (评价、工单、签收记录、码表、订单状态都还原到跑之前的样子)")
        return recs

    import rounds
    recs, _ = rounds.跑并收尾(跑一轮, 名="评价",
                              结果文件=os.path.join(HERE, "rating-eval-results.jsonl"),
                              全集数=len(CASES), 本轮数=len(cs))
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"最后一轮 通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/"
          f"{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/"
          f"{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}(最后一轮)")


if __name__ == "__main__":
    main()
