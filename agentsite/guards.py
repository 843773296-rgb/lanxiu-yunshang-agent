#!/usr/bin/env python3
"""回答体检 —— 把提示词里的「铁律」从祈使句变成强制。

系统提示里写了一堆规矩:只说查到的、查不到就说查不到、物料成本不是售价、
工期报最慢那个数、需补量不许猜码……**它们全是祈使句。**
模型照做与否,以前只能靠评测事后抽查 —— 而评测是抽样,漏掉的那些直接到了客户面前。

这个文件把它们接到 Agent SDK 的 hook 上:

  UserPromptSubmit  注入今天的日期(模型不知道今天几号,工期倒推会算错)
  PreToolUse        参数体检(客户说了「整幅」而模型传了「局部」→ 成本工期差 4 倍)
  PostToolUse       记下这一轮查过什么、查到了什么
  Stop              **交付前体检**,不合格打回重答
  PreCompact        压缩前立旗;下一轮把按号取过的单据和「压缩会丢事实」的提醒注回去

这就是这个项目一直在讲的那句话:
**Tool 是模型想起来才用,Hook 是不管它想不想都执行。**

体检逻辑写成**纯函数** `check_answer(text, calls)`,不依赖 SDK ——
所以能离线测(见 guards_test.py),不用花一分钱调模型。
"""
import datetime as dt, json, os, re, sys

# 数字型结论的识别
RE_MONEY = re.compile(r"(?:[¥￥]\s*|人民币\s*)([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*元")
RE_DAYS  = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[-–—~至到]\s*(\d+(?:\.\d+)?)\s*)?(?:个)?(?:工作日|日历天|天|工日)")
RE_SIZE  = re.compile(r"(?:推荐|建议|适合|应该穿|可以穿|选)\s*[「\"']?(S|M|L|XL|XXL|均码|\d{3})[」\"']?\s*码?")
# 身体尺寸(厘米 / 身高体重)。**2026-09-21 补的,补的是 g1 的一个洞**:
# g1 第一行是 `if not (monies or days): return None` —— 只有答案里出现**金额或工期**
# 才往下查「有没有调工具」。而成长推算的答案给的是**身高厘米数**(171.7cm),
# 既不是钱也不是天,于是那道体检**在第一行就放行了**。
# 评测里实测到:模型有时候一个工具都没调、14.6 秒就答完一个身高预测
# (正常轮次要 50 秒、调 2 个工具),而体检一路绿灯。
# g1 的注释自己写着「『该查的没查就答』是工具变多之后最高频的失败」——
# 那句话是对的,只是它当时只盖住了两类数字。
# 带单位的数:长度 / 重量 / 件数 / 积分 / 百分比。
# **这几类的共同点是「只能查出来」** —— 编一个出来看起来完全正常,而下游照着它做决定。
RE_BODY = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[-–—~至]\s*\d+(?:\.\d+)?\s*)?"
                     r"(?:cm|CM|厘米|公分|kg|KG|公斤|千克|件|分\b|%|％)")
# 身体尺寸类结论的信号词 —— 说到这些还给了厘米数,那一定是查过库才说得出来的
# ⚠️ **第一版这里是个身体词表,而那是在枚举词** —— CLAUDE.md 栽过十次的那条,
# 我今天刚把「判据落结构不枚举词」写进 skill,转头自己犯了第十一次:
# 词表里有「身高/胸围/腰围」,没有「裙长」,于是「PT04 的 M 码裙长 90cm」被放行。
#
# 结构判据长这样:**带单位的数,默认就是「查出来的量」,除非句子里有「做法动作词」。**
#   查出来的:身高 171.7cm、裙长 90cm、在手 42 件、余额 3200 分、转化率 62%
#   做法里的:裙长**留** 5cm 折边、袖长**放** 3cm、**加** 2cm 缝份
# 分界线不是「哪个部位」,是**这个数是被读到的,还是被决定的**。
# 反过来筛(默认拦、列出放行的动作词)比正着筛(默认放、列出该拦的名词)稳得多:
# 部位名有无数个,而「留/放/加/折/缩」这类动作词是有限的。
做法词 = ("留", "放", "加", "折边", "折起", "缝份", "余量", "放量", "缩", "减")

# **限定语里的数不算「查出来的量」** —— 它们本身就是「我不确定」的表达,
# 而那正是这道体检希望模型**说出来**的话。拦它等于惩罚模型说实话。
# 2026-09-21 夜实测误伤:`个体差 ±5cm 是常态` 里的那个 5 被判成「成衣尺码没查过」,
# 因为窗口扫到了下一句的「腰围」。
# ⚠️ 这条判据我一天里错了四次,每次都是同一个形状 ——
#   词表 → 做法动作词 → 点名工具 → **而「±」这个符号才是最强的结构信号**。
# 「±5cm」「区间 140–202cm」「误差 3cm」都长着「我不确定」的记号,
# 靠**符号和限定词**认,比靠部位名认稳得多。
限定记号 = ("±", "正负", "误差", "上下浮动", "左右浮动", "常态", "个体差", "波动")

# 整单结论的信号词 —— 只有给总量时才要求调过对应的算账工具
TOTAL_D  = ("整单", "总共", "一共", "交期", "工期", "多久", "大概要", "预计", "能拿到", "交付")
TOTAL_M  = ("总价", "合计", "报价", "价格", "多少钱", "售价", "要花")
PRICEY   = ("售价", "报价", "价格", "多少钱", "卖", "要花", "收")
HEDGE    = ("物料成本", "不含", "不是售价", "不是报价", "仅物料", "材料成本")
UNKNOWN  = ("查不到", "未录入", "没有录入", "尚未录入", "转工艺负责人", "未定义", "不清楚")
# 中文否定与子串**统一走 agent/textmatch.py** —— 原来四个文件各有一份词表,
# 每次踩坑只补一份,别的三份继续错。这里只留业务词表。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import re as _re
import textmatch as tm      # noqa: E402


def _业务今天():
    """业务上的今天(prompts._TODAY ← seed.TODAY)。**自己把仓库根放进 sys.path 再导** ——
    623b8e6 第一版在函数里直接 `from prompts import`,scheme_hook_test 那种只带 agentsite 的进程里
    报 ModuleNotFoundError,钩子整个炸掉(对方会话 check.sh 抓到)。导不到就返回 None,调用方退回说法。"""
    根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if 根 not in sys.path:
        sys.path.append(根)
    try:
        from prompts import _TODAY
        return _TODAY
    except Exception:
        return None
# 判「不可」的说法 —— 答案里没有这类断言时,g4 不该开火
DENY = ("不可", "做不了", "不能做", "不行", "没法做", "做不出", "无法做", "做不到")


def _num(s):
    try: return float(str(s).replace(",", ""))
    except (TypeError, ValueError): return None


def _near(text, idx, words, span=28):
    """idx 附近 span 字内有没有 words 里的词"""
    seg = text[max(0, idx - span): idx + span]
    return any(w in seg for w in words)


def _monies(text):
    out = []
    for m in RE_MONEY.finditer(text):
        v = _num(m.group(1) or m.group(2))
        if v is not None: out.append((v, m.start()))
    return out


def _days(text):
    out = []
    for m in RE_DAYS.finditer(text):
        a, b = _num(m.group(1)), _num(m.group(2))
        out.append((a, b, m.start()))
    return out


def _bodies(text):
    out = []
    for m in RE_BODY.finditer(text):
        v = _num(m.group(1))
        if v is not None: out.append((v, m.start()))
    return out


def days_pos(days):
    """把 `_days` 的 (起, 止, 位置) 压成 (值, 位置) —— 上面那个循环要统一形状。"""
    return [(a, i) for a, _b, i in days]


def _called(calls, name):
    return [c for c in calls if c.get("tool", "").endswith(name)]


def _res(c):
    r = c.get("output")
    if isinstance(r, str):
        try: r = json.loads(r)
        except Exception: return {}
    return r if isinstance(r, dict) else {}


# 哪种数该由哪个工具给出 —— **点名工具,而不是只看「有没有调工具」**。
#
# ⚠️ 2026-09-21 夜发现:新补的那一类只有「一个工具都没调」这一个判据,
# 于是**随便调了个不相干的工具就放行**(实测:调 kb_tables 之后报身高、
# 报库存、报积分,三类全过)。
# 而实际情况恰恰相反:**模型很少一个工具都不调,它更常见的是调了几个、
# 但没调对的那个** —— 今天 G04 有一轮就是「调了 kb_size、kb_fit、kb_fit」,
# 没调 forecast_growth。
#
# > **补了一半的防线,拦得住最罕见的那一档,拦不住最常见的那一档。**
#
# 金额和工期没这个问题,因为它们从一开始就点名了工具(kb_bom / kb_lead)。
# 下面给其余几类补上。每条:(信号词, 该调的工具们, 这类数叫什么)
数的出处 = [
    # ⚠️ **跨类词要在两边都列出来。** 「胸围/腰围/围度」既是人体尺寸
    # (forecast_growth 给)又是成衣尺码(kb_size 给)—— 只列在一边的话,
    # 查了另一边的人会被误拦。2026-09-21 夜误伤过两条成长推算的正例。
    # 判据是「把命中的所有档的工具并起来,调过任意一个就算」,
    # **而并集只在这个词两边都列了的时候才生效** —— 这是那条判据的隐含前提,写在这儿。
    (("身高", "成年身高", "长到", "突增", "围度", "胸围", "腰围", "臀围"),
     ("forecast_growth", "plan_for_event"), "身高推算"),
    (("库存", "在手", "可发", "备货"), ("get_stock", "stock_alert"), "库存量"),
    (("积分", "积分余额"), ("points_ledger", "get_member"), "积分"),
    (("转化率", "客单价", "投入产出", "ROI", "获客成本"),
     ("appt_funnel", "channel_compare", "activity_roi", "monthly_review"), "经营指标"),
    (("产能", "排期", "排到", "负载"), ("get_capacity",), "产能排期"),
    # ⚠️ 这两条是**新加的覆盖检查当场抓出来的** —— 我列上面五条时凭的是印象,
    # 而印象里漏了「成衣尺码」和「面料门幅」,偏偏这两类恰恰是这个项目的本行。
    # **列清单靠印象必漏,靠检查才点得全。**
    (("裙长", "衣长", "通袖", "袖长", "肩宽", "胸围", "腰围", "领围", "尺码表", "成衣"),
     ("kb_size", "kb_fit", "grading_audit"), "成衣尺码"),
    (("布幅", "门幅", "幅宽", "用料", "米数"),
     ("kb_bom", "kb_material", "pattern_queue"), "面料门幅/用料"),
]


# ── 体检项 ──────────────────────────────────────────────────────────────
def g1_no_source(text, calls):
    """给了数字结论,却没查过 —— **「该查的没查就答」是工具变多之后最高频的失败**,
    而它恰恰是评测集最难覆盖的:答案看起来完全正常,只是那个数字是编的。"""
    monies, days = _monies(text), _days(text)
    # 带单位的数**默认算「查出来的」**,只有贴着做法动作词才不算
    # (「裙长留 5cm 折边」是决定,不是查来的数)
    bodies = [(v, i) for v, i in _bodies(text)
              if not _near(text, i, 做法词) and not _near(text, i, 限定记号, span=10)]
    if not (monies or days or bodies): return None
    if not calls:
        哪 = ("金额/工期" if (monies or days) else "尺寸/件数/积分/百分比这类**只能查出来**的数")
        return (f"答案里给了具体数字({哪}),但这一轮**一个工具都没调** —— "
                f"数字没有出处,不能这么答")
    # 点名:这类数该由这几个工具里的某一个给出。
    #
    # ⚠️ **一个数可能同时命中好几档** —— 「胸围」既是人体尺寸(forecast_growth 给)
    # 又是成衣尺码(kb_size 给)。按词分类时**总会有词跨类**,
    # 2026-09-21 夜就这么误伤了两条成长推算的正例:答案里提了「围度」,
    # 调的是 forecast_growth(对的),却被成衣尺码那一档判成没查过。
    #
    # 所以判据是:**把这个数命中的所有档的工具并起来,调过其中任意一个就算有出处。**
    # 「这个数可能从这几处来,而他查过其中一处」—— 那就不该拦。
    # (代价:一个数同时属于两类时,查了其中一类就放行。宁可漏,不可误 ——
    #  误拦会让体检被关掉,而关掉之后它挡的所有错会一起回来。)
    for v, i in (monies + days_pos(days) + bodies):
        命中 = [(工具们, 叫什么) for 词们, 工具们, 叫什么 in 数的出处
                if _near(text, i, 词们)]
        if not 命中:
            continue
        可接受 = {t for 工具们, _ in 命中 for t in 工具们}
        if not any(_called(calls, t) for t in 可接受):
            叫 = " / ".join(sorted({x for _, x in 命中}))
            return (f"答案给了{叫}({v:g}),但**没调 {' / '.join(sorted(可接受))} "
                    f"里的任何一个** —— 调了别的工具不等于查过了这个数")
    for v, i in monies:
        if _near(text, i, TOTAL_M) and not _called(calls, "kb_bom"):
            return f"答案报了总价/报价(¥{v:g}),但没调 kb_bom 算过 —— 价格不能凭印象说"
    for a, b, i in days:
        if _near(text, i, TOTAL_D) and not _called(calls, "kb_lead"):
            return f"答案给了整单工期({a:g} 天),但没调 kb_lead 算过 —— 工期不能凭印象说"
    return None


def g2_cost_as_price(text, calls):
    """物料成本不是售价。提示词里写了,这里强制。"""
    for c in _called(calls, "kb_bom"):
        cost = _res(c).get("物料成本")
        if cost is None: continue
        for pat in (f"{cost:g}", f"{int(cost)}", f"{int(cost):,}"):
            i = text.find(pat)
            if i < 0: continue
            if _near(text, i, PRICEY) and not _near(text, i, HEDGE, span=45):
                return (f"把物料成本 ¥{cost:g} 当成售价说了 —— 它不含工时、门店成本与税,"
                        "必须写明「这是物料成本,不是报价」")
    return None


def g3_lead_single(text, calls):
    """工期必须报区间,而且对客户报最慢那个数。"""
    for c in _called(calls, "kb_lead"):
        r = _res(c)
        fast, slow = r.get("最快天数"), r.get("最慢天数")
        if fast is None or slow is None or fast == slow: continue
        ds = _days(text)
        if not ds: continue
        has_slow = any(abs((a or 0) - slow) < 1 or abs((b or 0) - slow) < 1 for a, b, _ in ds)
        has_fast = any(abs((a or 0) - fast) < 1 or abs((b or 0) - fast) < 1 for a, b, _ in ds)
        if has_fast and not has_slow:
            return (f"只报了最快的 {fast} 天,没报最慢的 {slow} 天 —— "
                    "**对客户报最慢那个数**,余量留给自己")
        if not has_slow and not has_fast:
            return f"答案里的天数和 kb_lead 算出的 {fast}–{slow} 天对不上,数字是哪来的"
    return None


def g4_no_rule(text, calls):
    """判「不可」必须说得出依据 —— 它挡的是客户的单子。"""
    for c in _called(calls, "kb_combo"):
        r = _res(c)
        if r.get("verdict") != "不可": continue
        # 只有答案**真的下了「不可」这个断言**时才要求给依据。
        # 查过但没在答案里下结论(比如顺带查了一下)不算违规 ——
        # 而且判断「答案在说这一对」要认工艺名,不能认面料名:
        # 面料名「纱」是「香云纱」的子串,认它会把不相干的回答一起误伤。
        if not any(w in text for w in DENY): continue
        if r.get("craft") and r["craft"] not in text: continue
        rule, reason = r.get("rule") or "", r.get("reason") or ""
        if rule and rule in text: continue
        if reason and any(k in text for k in re.findall(r"[一-龥]{4,}", reason)[:4]):
            continue
        return (f"判了「{r.get('craft')} × {r.get('material')} 不可」却没说依据 —— "
                f"依据是 [{rule}] {reason[:40]}")
    return None


def g5_fit_guess(text, calls):
    """需补量却猜码 —— 数据不够时硬给答案,是最危险的一种错。"""
    for c in _called(calls, "kb_fit"):
        if _res(c).get("档位") != "需补量": continue
        m = RE_SIZE.search(text)
        if m and not tm.negated(text, m.start()):
            return (f"kb_fit 判的是「需补量」,答案却推荐了 {m.group(1)} 码 —— "
                    "**不许按身高体重猜**,要请客户补量")
    return None


def g6_undefined(text, calls):
    """相容矩阵返回「未定义」时,必须如实说查不到,不得自行推断。"""
    for c in _called(calls, "kb_combo"):
        if _res(c).get("verdict") != "未定义": continue
        if not any(w in text for w in UNKNOWN):
            return "相容矩阵这一格是「未定义」,答案却给了肯定/否定判断 —— 必须如实说查不到"
    return None


def g7_rush_promise(text, calls):
    """不能靠加人压缩的工序(织造、染色晾晒、手绘顾绣发绣),加急要求必须当场拒绝。"""
    hard = []
    for c in _called(calls, "kb_lead"):
        for w in _res(c).get("风险") or []:
            if any(k in w for k in ("加人无效", "除不动", "不能靠加人", "只能一个人")): hard.append(w)
    if not hard: return None
    for m in re.finditer(r"(可以加急|能加急|加钱可以|能赶出来|可以赶|能提前)", text):
        if not tm.negated(text, m.start()):
            return (f"关键路径上有**不能靠加人压缩**的工序({hard[0][:24]}),"
                    "却答应了加急 —— 这类要求要当场拒绝,不要先答应再想办法")
    return None


# 具体事实的断言信号:提到了某一单/某一件,而不是在讲流程
SPECIFIC = ("您的", "你的", "这一单", "这单", "这件", "该订单", "此单", "您这")
# 系统里的状态名 + 口语说法。**只认系统状态名会漏掉大半** ——
# 顾问不会说「您这单是已发货」,会说「您这单已经发货了」。
ORDER_ST = ("待付款", "待审核", "待生产", "生产中", "已生产", "待发货", "已发货",
            "待完成", "已完成", "已取消", "方案确认中", "待收货", "已关闭",
            "发货了", "发出了", "寄出了", "到货了", "签收", "在生产", "在做了",
            "付款了", "付过款", "已付", "取消了", "做好了", "完成了")
STOCK_W  = ("有现货", "有货", "没货", "缺货", "零库存", "还有库存", "库存充足", "现货充足")
AFTER_W  = ("退款成功", "退款失败", "已退款", "退货已", "换货已", "审批同意", "审批拒绝", "已入库")
RE_ORDID = re.compile(r"\b\d{16,20}\b")


def g8_business_fact(text, calls):
    """订单状态、库存、售后进度 —— **这三样绝不能凭印象答**。

    和 g1 只管数字不同,这里管的是**状态断言**:「您这单已发货」听起来不像数字,
    但它一样是一个查得到、也必须查过才能说的事实。说错了客户当场就发现。

    只在答案确实指向某一单/某一件时开火(带单号,或带「您的/这一单/这件」这类指代)——
    讲流程、讲规则时提到这些词不算。
    """
    specific = bool(RE_ORDID.search(text)) or any(w in text for w in SPECIFIC)
    if not specific: return None
    if any(w in text for w in ORDER_ST) and not _called(calls, "get_order"):
        return "答案里给了某一单的状态,但没调 get_order 查过 —— 订单状态不能凭印象说"
    for w in STOCK_W:
        i = text.find(w)
        if i >= 0 and not _called(calls, "get_stock"):
            return f"答案里断言了库存(「{w}」),但没调 get_stock 查过 —— 现货不能凭印象说"
    if any(w in text for w in AFTER_W) and not (
            _called(calls, "get_aftersale") or _called(calls, "get_refund_trace")):
        return "答案里给了售后进度,但没调 get_aftersale 查过 —— 售后状态不能凭印象说"
    return None


# 报价单的识别信号 —— 三个以上才算,避免把普通答复误判成报价单
QUOTE_SIG = ("报价单", "方案报价", "物料成本", "用料清单", "工期", "免责", "有效期",
             "尺码建议", "可行性")
# 「任何报价单都必须有」的两条
MUST_ALWAYS = [
    (("不是最终报价", "非最终报价", "不含工时", "不是报价", "不构成报价"),
     "没写明「物料成本不是最终报价、不含工时与门店成本」"),
    (("区间", "最慢", "以最慢", "估算"),
     "没写明工期是区间估算、以最慢值为准"),
]


def g9_quote_disclaimer(text, calls):
    """报价单**会被截图转发**,脱离对话独自存在 —— 所以必须自带完整前提。

    少一句免责,三个月后客户翻出来问「你们当时说 xx 的」,就是一场纠纷。
    Skill 里写了该有哪几条;这里保证它真的有。
    **Skill 提供格式,Hook 保证格式被遵守** —— 少了后半句,格式只是建议。
    """
    if sum(1 for w in QUOTE_SIG if w in text) < 3: return None
    miss = [why for words, why in MUST_ALWAYS if not any(w in text for w in words)]
    # 按方案里的实际情况追加必须写的话
    for c in _called(calls, "kb_combo"):
        if _res(c).get("verdict") == "需评估" and not any(
                w in text for w in ("不构成承诺", "须工艺负责人", "须打样", "评估通过前")):
            miss.append("组合是「需评估」,却没写明评估通过前不构成承诺")
    for c in _called(calls, "kb_fit"):
        if _res(c).get("档位") == "需补量" and "补量" not in text:
            miss.append("尺码档位是「需补量」,报价单里没写明补量后才能开工")
    if any(w in text for w in ("香云纱", "晒莨")) and not any(
            w in text for w in ("雨季", "日照", "天气")):
        miss.append("用了香云纱/晒莨,没提示雨季可能延期")
    if miss:
        return "这是一份会被转发出去的报价单,但免责前提不全:" + ";".join(miss)
    return None


# ── 成长推算相关的四条 ─────────────────────────────────────────────────
# 这一组守的都是同一件事:**推算的诚实边界不能在转述时被抹掉。**
# 工具返回里带着区间、限定、冲突标记、过期标记 —— 它们是返回值的一等公民,
# 但**从工具到客户中间隔着一个模型**,模型天然倾向于把话说得干净利落。
# 「142.3cm」比「137.8 到 146.8」好听得多,而后者才是真话。

def g21_apply_as_done(text, calls):
    """**提了审批单,不许说成「已经改好了」。**

    `apply_adjust` 只建了一张单,客户档案一个字没动;
    真正生效要等总部运营批,批完还要走实际的调整动作。
    模型说成「已改为黑金」,用户会照着这句话去跟客户讲,而客户查不到。

    ⚠️ 判据要绕开中文那个坑:**顶回一件事必须先把它说出来** ——
    「**不能**直接改成黑金,得提审批」里也有「改成黑金」。
    所以查的是「**未被否定的**完成态说法」,而且**引号里的不算**
    (引号里是被提及的词,不是被主张的事)。
    """
    if not _called(calls, "apply_adjust"):
        return None
    t = _strip_quotes(text or "")
    # **不枚举短语,查结构。** 第一版写的是「已经改成 / 已改为 / …」这样的整串,
    # 而模型说的是「已经**把 C10001** 改成黑金」—— 完成态标记和动作
    # **中间隔着宾语**,整串接不上。这个项目在枚举中文说法上栽到第十二次了。
    #
    # 结构是:**同一个小句里,既有完成态标记,又有「改动生效」的动作。**
    # 小句边界是标点(textmatch 的 in_clause 按标点断),所以
    # 「不能直接改成黑金,我已提交申请」里,前半句没有完成态标记、
    # 后半句的动作是「提交」不是「改成」,两边都不命中。
    for 动作 in ("改成", "改为", "调成", "调整为", "升为", "升级为", "变成", "生效"):
        if tm.in_clause(t, 动作, ("已经", "已", "完成"), both=True) and \
                not tm.negated(t, t.find(动作), span=20, both_sides=True):
            return (f"「{动作}」那句带着完成态,但 `apply_adjust` "
                    f"**只是提交了一张审批单** —— 客户档案一个字没改。"
                    f"用户会照着这句去跟客户讲,而客户查不到。"
                    f"改成「已提交申请,等总部运营审」。")
    return None


def _strip_quotes(text):
    """挖掉引号里的内容 —— **引号里是被提及的词,不是被主张的事**。

    「待审批 → **已生效**」这种引用状态名的写法,不该被当成「它说生效了」。
    """
    out = text or ""
    for a, b in (("「", "」"), ("『", "』"), ("\u201c", "\u201d"), ("`", "`")):
        parts, i = [], 0
        while True:
            j = out.find(a, i)
            if j < 0: parts.append(out[i:]); break
            k = out.find(b, j + len(a))
            if k < 0: parts.append(out[i:]); break
            parts.append(out[i:j]); i = k + len(b)
        out = "".join(parts)
    return out


def _fc(calls):
    """取成长推算类工具的返回。plan_for_event 的字段名带前缀,统一成一份。"""
    out = []
    for c in _called(calls, "forecast_growth") + _called(calls, "plan_for_event"):
        r = _res(c)
        if not isinstance(r, dict) or r.get("error"): continue
        out.append(dict(h=r.get("预测身高") or r.get("穿那天预测身高"),
                        rng=r.get("区间") or r.get("身高区间"),
                        girth=r.get("围度区间"),
                        conflict=(r.get("靶身高校验") or {}).get("需人工确认"),
                        warn=r.get("提醒") or []))
    return out


def g10_point_no_range(text, calls):
    """报了预测身高却没报区间。**只给点估计等于骗人。**

    区间不是附注,是这个结论的精度本身 —— 抹掉它,家长会以为「就是 142.3」,
    然后按 142.3 定做,而真实落点可能在 137.8。**小了没法救。**
    """
    for f in _fc(calls):
        if not f["h"] or not f["rng"]: continue
        if not tm.mentions(text, f"{f['h']:g}"): continue        # 压根没提这个数,不管
        lo, hi = f["rng"]
        # **只认端点数字或明确的 ± 表述。**
        # 不认「区间」这个词 —— 踩过:答案里那个「区间」是在说围度,
        # 身高照样被当成确定值说了出去。**词在,不代表它在限定这件事。**
        if tm.mentions(text, (f"{lo:g}", f"{hi:g}")): continue
        if re.search(r"[±±]\s*\d|浮动\s*\d|上下\s*\d", text or ""): continue
        return (f"你把预测身高 {f['h']:g}cm 当成一个确定值说了,却没给区间 "
                f"{lo:g}–{hi:g}cm。**只报点估计等于骗人** —— "
                "推的是统计分布不是这个孩子。把区间一起说出去。")
    return None


def g11_girth_point(text, calls):
    """给了围度点估计,或者没说围度必须复量。

    身高受遗传主导可推,围度受营养运动影响 —— **同一个身高能对应差很多的围度**。
    拿推算围度去裁,是这套系统里最容易造成报废的一步。
    """
    for f in _fc(calls):
        if not f["girth"]: continue
        w = tm.mentions(text, ("胸围", "腰围", "臀围"))
        if not w: continue
        # **限定必须和围度在同一小句里。** 踩过:「复量」写在说身高的那句上,
        # 围度那句只有「也一并算好了」,体检却因为整段里有「复量」而放行。
        if tm.in_clause(text, w, ("区间", "范围", "复量", "再量", "不得直接", "不能直接")):
            continue
        return ("你说了围度却没说它只是一个区间、必须复量。"
                "**围度不给点估计,更不能照着裁** —— 同一个身高能对应差很多的围度。")
    return None


def g12_expired_ignored(text, calls):
    """量体已过期,却没让客户复量就往下说。

    「有个旧尺寸总比没有强」是童装返工的来源。**超期的记录是无效值,不是参考值。**
    """
    stale = False
    for c in _called(calls, "get_wearer"):
        r = _res(c)
        for w in (r.get("着装人") or []) if isinstance(r, dict) else []:
            if (w.get("量体是否过期") or {}).get("过期"): stale = True
    for f in _fc(calls):
        if any("无效记录" in w or "已过" in w for w in f["warn"]): stale = True
    if not stale: return None
    if tm.says(text, ("复量", "再量一次", "重新量", "回店量")): return None
    return ("这个着装人的量体记录**已经过期**,你却没提复量。"
            "超期的量体是无效值不是参考值 —— 下单前必须先约复量。")


def g13_target_conflict(text, calls):
    """遗传身高和百分位推算差太多,却自己挑了一边。

    和客户合并判断是同一条道理:**两个口径打架时自动挑一边都是猜。**
    """
    for f in _fc(calls):
        if not f["conflict"]: continue
        if tm.says(text, ("人工", "版师", "转专业", "两个口径", "存在分歧")): continue
        return ("遗传身高与百分位推算差得较多(工具已标「需人工确认」),"
                "你却给了一个确定结论。**不要自己挑一边** —— 说明分歧并转人工。")
    return None


PLAN_SIG = ("成长方案", "留成长量", "折边", "最晚下单", "复量日", "穿那天",
            "预测身高", "跨档")
# 「任何成长方案都必须有」的四条
PLAN_MUST = [
    (("区间", "–", "—", "到"), "没给身高区间 —— 只报点估计等于把统计分布说成承诺"),
    (("复量", "再量", "重新量"), "没写复量安排 —— 方案的准头全靠临下单前那一次量体"),
    (("折边", "留量", "系带", "不留"), "没写留成长量 —— 汉服能靠折边多穿一季,这是这份方案的价值所在"),
    (("个体差", "统计", "不是这个孩子", "±", "分布"),
     "没写「推的是统计分布不是这个孩子」—— 家长会把预测值记成承诺"),
]


BYPASS = ("直接重新发起", "直接重发", "再发起一次", "重新发起退款", "直接退给",
          "跳过审批", "不用审批", "无需审批", "不必审批", "绕过审批",
          "沿用原幂等号", "复用幂等号", "换个幂等号再试", "多试几次", "再重试几次")
# 这几个词出现时,说明答案里已经带着必要的前提,不算绕过
GUARD_WORDS = ("审批", "店长", "复核", "核对", "确认后", "渠道核实", "不得", "先查")


# **强信号 = 结论本身**,出现一个就是一份判责;
# 弱信号只是在谈这件事,要两个才算。
# 一开始一律按「两个才算」,结果「属于面料特性,**无责**」这种只带一个词的
# 结论被放行了 —— 而它恰恰是最该拦的那种:无责也是判责,同样对着钱。
LIAB_HARD = ("免费返修", "免费改", "收费改", "让步处理", "无责",
             "按合同分担", "我方责任", "客方责任")
LIAB_SOFT = ("判责", "责任归", "客方", "返修判定", "我方", "责任在")
CONFIRM = ("人工确认", "待确认", "由店长", "须确认", "不构成承诺", "以门店最终",
           "需客服确认", "转人工", "草稿", "供参考")


# 形制词一出现就是结论 —— 观察词只是特征
XZ_WORDS = ("马面裙", "襦裙", "褙子", "大袖衫", "半臂", "曳撒", "圆领袍", "百迭裙",
            "立领长衫", "披风", "唐制", "宋制", "明制", "齐胸", "齐腰")
# ⚠️ 名字不能叫 HEDGE —— 上面 g2 已经有一个 HEDGE(装的是「不含工时」这类免责词)。
# 第一版就叫了 HEDGE,把它覆盖掉,于是 g2 丢了豁免词开始误伤两条正确答案。
# **同名常量被后定义的覆盖,不报错、不警告,只是前面用它的函数悄悄换了行为。**
VISION_HEDGE = ("看起来像", "可能是", "疑似", "初步判断", "不确定", "要确认", "需确认",
                "无法确定", "看不出", "请确认", "补拍", "先确认", "假设", "待查证")
PRICE_WORDS = ("报价", "价格", "多少钱", "工期", "天能做", "元", "¥")


ACCT_WORD = {"锁定": ("锁定", "解锁", "身份核验"),
             "注销中": ("注销", "冷静期", "撤回"),
             # ⚠️ 「查不到」**不算交代**。第一版把它放进来,结果
             # 「系统里查不到,您把三围报一下就行」蒙混过关 ——
             # 而那正是最危险的一句:**把刚删掉的个人数据又收一遍**,
             # 客户根本没重新同意过。「查不到」是症状,不是交代。
             "已注销": ("注销", "已删除", "重新注册")}
# 已注销之后**绝不能**做的事:让客户口头重报个人数据
REASK = ("报一下", "报给我", "说一下尺寸", "告诉我三围", "重新报", "口头报")


def g19_account_state(text, calls):
    """账户处在锁定 / 注销中 / 已注销,答案却当没这回事。

    这三种状态**会挡住业务**:锁定不能在电话里绕过,注销中不该推新订单,
    已注销的尺寸是**真的删了**,不是「查一下就有」。

    最危险的是最后一种:顾问会顺口说「您把尺寸报一下就行」——
    **那等于把刚删掉的个人数据又收一遍**,而客户根本没重新同意过。
    """
    for c in _called(calls, "get_wearer"):
        r = _res(c)
        for w in (r.get("着装人") or []) if isinstance(r, dict) else []:
            a = w.get("账户") or {}
            st = a.get("状态")
            if st == "已注销" and tm.mentions(text, REASK):
                return ("账户**已注销,个人数据已按客户要求删除**,"
                        "你却让客户口头把尺寸再报一遍 —— "
                        "**那等于把刚删掉的数据又收一遍**,而客户没有重新同意过。"
                        "要下单请先请客户重新注册并重新取得同意。")
            if st in ACCT_WORD and not tm.mentions(text, ACCT_WORD[st]):
                return (f"这个账户是「{st}」状态,答案里一个字都没提。"
                        f"{a.get('该怎么办', '')[:60]}"
                        " —— 状态是给**行动**看的,不说出来等于没查。")
    return None


def g20_consent_version(text, calls):
    """协议改版了没重新取得同意,却继续推进下单。

    **改了条款而没重新取得同意,等于没同意。** 这不是形式:
    条款里写的正是「我们能拿你的数据做什么」,版本变了而人没点过头,
    后面所有基于那份同意的处理都站不住。
    """
    hit = False
    for c in _called(calls, "get_wearer"):
        r = _res(c)
        for w in (r.get("着装人") or []) if isinstance(r, dict) else []:
            if (w.get("账户") or {}).get("协议需重新取得同意"): hit = True
    if not hit: return None
    if tm.mentions(text, ("重新确认", "重新同意", "协议", "条款", "隐私政策")): return None
    if not tm.mentions(text, ("下单", "开工", "安排生产", "可以做", "报价")): return None
    return ("这个账户的服务条款或隐私政策已改版、还没重新取得同意,"
            "而你已经在谈下单了。**改了条款而没重新取得同意,等于没同意** —— "
            "先让客户在小程序上重新确认。")


def g18_vision_conclusion(text, calls):
    """看了图就直接下形制结论,或者只凭图报价。

    **图给的是特征,不是结论。** 一张照片分不出唐制大袖衫和宋制褙子 ——
    光线、角度、褶皱都会骗人,而模型天然想跳过「查证」那一步,
    因为「这是明制马面裙」比「看起来像马面裙,要确认」好听得多。

    价钱和工期更危险:它们取决于**面料与工艺**,
    而那两样**照片里根本看不出来** —— 只凭图报价是纯粹的编。
    """
    if not _called(calls, "__vision__") and "[图片]" not in (text or ""):
        # 这一条只在带图的那一轮生效。带图与否由调用方在文本里打标记,
        # 或者由 vision_eval 直接调 check_answer 时传进来。
        pass
    xz = tm.mentions(text, XZ_WORDS)
    if not xz: return None
    tools = " ".join(c.get("tool", "") for c in (calls or []))
    verified = any(k in tools for k in ("kb_lookup", "kb_pattern", "kb_detail", "kb_tables"))
    if not verified and not tm.mentions(text, VISION_HEDGE):
        return (f"你看图直接给了形制结论「{xz}」,既没查证也没加限定。"
                "**图给的是特征,不是结论** —— 一张照片分不出唐制大袖衫和宋制褙子。"
                "要么用 kb_lookup / kb_pattern 查证,要么说「看起来像…,需确认」。")
    if tm.mentions(text, PRICE_WORDS) and not verified:
        return ("你只凭一张图就谈了价钱或工期。**价钱和工期取决于面料与工艺,"
                "而那两样照片里根本看不出来** —— 必须先问客户或查库。")
    return None


def g17_liability_promise(text, calls):
    """判责结论直接当承诺发出去。

    09-养护与售后.md 第六节把这条写死了:
    **「助手查记录、给判据、拟话术;人做决定」—— 涉及退换和赔付,结论必须由人给。**

    为什么这条要单独立一道:判责的每一个结论**都对着钱**。
    「我方,免费返修」被顾问原样念给客户,就等于商家已经认了责 ——
    **认责这件事没有回退键**,后面再想改口,代价是信任而不是钱。
    """
    hard = sum(1 for w in LIAB_HARD if w in text)
    soft = sum(1 for w in LIAB_SOFT if w in text)
    if hard < 1 and soft < 2: return None
    if tm.mentions(text, CONFIRM): return None
    return ("这是一份判责结论,但没写明**须由人确认后执行**。"
            "判责每一条都对着钱 —— 「我方,免费返修」被原样念给客户,"
            "就等于商家已经认了责,而**认责没有回退键**。"
            "草稿里必须带上「须由店长/客服确认后执行,本结论不构成承诺」。")


def g16_bypass_control(text, calls):
    """建议绕过审批链 / 幂等号 / 重试上限。**这条涉及钱。**

    边界审计点名的缺口:这条原来**只有提示词守着** —— 而提示词是祈使句,
    模型多数时候会听,但「多数时候」不是边界。

    退款重发是这套系统里唯一能把钱弄出去的动作:
    幂等号复用会重复退款,跳过审批会绕开双人复核,
    而两者出事之后**都不可逆**。
    """
    w = tm.says(text, BYPASS)
    if not w: return None
    # **句号级**作用域,不是逗号级 —— 审批前提天然跨逗号:
    # 「核对渠道流水确认未到账后,可由客服重新发起退款,须经店长复核。」
    # 前提在前半句和后半句,用逗号级窗口会把这条合规的答案误拦。
    if tm.in_sentence(text, w, GUARD_WORDS): return None
    if tm.says(text, ("不得" + w, "不要" + w, "禁止" + w)): return None
    return (f"你建议了「{w}」,而同一句里没有任何前提(审批 / 店长复核 / 渠道核对)。"
            "**退款重发是这套系统里唯一能把钱弄出去的动作** —— "
            "幂等号复用会重复退款,跳过审批会绕开双人复核,两者都不可逆。"
            "必须写明:须由客服或店长发起、店长复核。")


def g15_growth_plan_sections(text, calls):
    """成长方案**会被转发给另一位家长看**,所以必须自带完整前提。

    它比报价单更危险:报价单说错了当场能对账,
    **成长方案说错了要等衣服做出来那天才知道,而那时料已经裁了。**

    Skill 里写了该有哪六段;这里保证它真的有。
    **Skill 提供格式,Hook 保证格式被遵守** —— 少了后半句,格式只是建议。
    """
    if sum(1 for w in PLAN_SIG if w in text) < 3: return None
    miss = [why for words, why in PLAN_MUST if not any(w in text for w in words)]
    if miss:
        return "这是一份会被转发出去的成长方案,但必备内容不全:" + ";".join(miss)
    return None


def g14_consent_bypass(text, calls):
    """工具因为缺同意拒绝了,答案却照样给了身体数据结论。

    身体数据与未成年人信息是敏感个人信息。**工具拒绝就是拒绝**,
    不能用训练知识补一个数糊过去 —— 那等于绕开了同意。
    """
    refused = [c for c in (calls or [])
               if isinstance(_res(c), dict) and "同意" in str(_res(c).get("error", ""))]
    if not refused: return None
    if tm.mentions(text, "同意"): return None
    if re.search(r"\d{2,3}(\.\d)?\s*(cm|厘米|公分)", text or ""):
        return ("工具因为**缺少同意**拒绝提供身体数据,你却报了身高数字。"
                "不能用训练知识补一个数糊过去 —— 照实说需要补同意。")
    return None


# 库里的量纲字段名 —— 取自 `measure_item.name` 和 `size_spec.item`。
# **手写在这儿是因为体检必须是纯函数(离线可测,不碰数据库)**,
# 而手写的东西会过期 —— 所以 `guards_test` 拿库里那两张表对一遍,少一个就红。
量纲字段 = ("身高", "体重", "胸围", "胸上围", "腰围", "臀围", "肩宽", "通袖长",
            "袖长", "衣长", "上襦衣长", "裙长", "裙腰围", "领围", "臂围", "裤长",
            "头围", "腕围", "脚长", "马面宽", "马面宽度", "占比", "米数", "档差",
            "尺码", "裁片", "用料")


def g22_agree_without_reading(text, calls, prompt=""):
    """**没查就同意** —— 「无出处的数字」那条的另一半。

    `g1_no_source` 抓的是「报了数字却没调工具」,而**换个不带数字的说法就漏**：
    这句缺口早就写在 `安全边界审计` 里,直到版师评测把它撞出来 ——

        版师:「童款 110 和 140 的胸围都是 72,看来童装本来就不用分码」
        助手:「**你这个发现对。**」(一个工具都没调)

    它没报任何数字,它只是**把对方的数当成了既成事实**,然后顺着往下推。
    实测连挂 5 次,**补一条铁律之后再跑两次还是挂** —— 提示词治不了它。
    这个项目为这件事立过规矩:**祈使句治不了的,交给闸。**

    ## 判据由三个各自客观的事实合成,不枚举「同意」有多少种说法

        ① 用户那句话里有一个**可以去库里核的断言**(实体编号 / 数值 + 库里的字段词)
        ② 这一轮**一个读工具都没调**
        ③ 回答里出现了**认同标记**,而且那个认同没有被否定

    ③ 用的是**封闭小类**(对 / 是的 / 确实 / 没错 / 说得对),不是「同意的说法」——
    这两件事差别很大:表达立场的方式接近无限(这个项目为枚举它栽过九次),
    而**句首的认同虚词就那么几个**。既有的 `opens_with_rejection` 是同一个形状。

    ## 三条必须**同时**成立,少一条都会误伤

    只看 ②(没调工具就打回)会把**正确答案**打回去 ——
    「改版型不归我管」本来就不需要查库,而它恰恰是版师那套 N05 的标准答案。
    只看 ③ 会把「**你说得对,我这就去查**」打回去 —— 那也是对的。
    """
    if calls: return None                       # ② 查过了,同意就是同意
    # ① 用户的话里有没有可核的断言 —— **一个数,挨着一个库里的字段名**。
    #
    # 第一版要求数字后面跟单位(「72cm」),而真实那句是「**胸围都是 72**」——
    # 中文里报尺寸经常不带单位,判据当场落空。
    # **这个列表是字段名,不是说法** —— 它和「枚举中文说法」不是一回事:
    # 表达立场的方式接近无限,而库里有哪几个量纲字段是**有限且查得到的**。
    # `guards_test` 会拿库里的 `measure_item.name` + `size_spec.item` 对一遍,
    # 少一个就红 —— 手写的列表配一道对账,才不会悄悄过期。
    if not (_re.search(r"(PT\d{2}|C\d{5}|W\d{5}|LT\d{2}|MT\d{2}|KF\d{2}|\d{15,})", prompt or "")
            or _re.search(r"\d+(\.\d+)?\s*(cm|厘米|米|%|码|片|条|天|元)", prompt or "")
            or (_re.search(r"\d", prompt or "")
                and any(w in (prompt or "") for w in 量纲字段))):
        return None
    # ③ 回答里有没有**没被否定的**认同标记
    认同 = ("你说得对", "您说得对", "说得对", "你这个发现对", "这个发现对",
            "确实是这样", "确实如此", "没错", "是的", "对的", "确实")
    hit = tm.says((text or "")[:160], 认同)     # 只看开头 —— 认同是开场白
    if not hit: return None
    return ("这一轮**一个工具都没调**,而你已经认同了对方给的说法"
            f"(「{hit}」)。对方报的数可能对,也可能看串了行 —— "
            "**在你自己查过之前,不要顺着它往下推结论**。"
            "先调工具核一遍,再说对不对。")


CHECKS = [g1_no_source, g2_cost_as_price, g3_lead_single, g4_no_rule,
          g5_fit_guess, g6_undefined, g7_rush_promise, g8_business_fact, g9_quote_disclaimer,
          g10_point_no_range, g11_girth_point, g12_expired_ignored, g13_target_conflict, g14_consent_bypass,
          g15_growth_plan_sections, g16_bypass_control,
          g17_liability_promise, g18_vision_conclusion,
          g19_account_state, g20_consent_version, g21_apply_as_done,
          g22_agree_without_reading]


def check_answer(text, calls, prompt=""):
    """返回违规清单。空清单 = 通过。纯函数,可离线测。

    `prompt` 是 2026-09-14 加的:有一类失败**只看回答看不出来** ——
    「你这个发现对」单独看完全正常,错就错在**对方那句话里有个没人核过的数**。
    判这种得把问句一起看。旧调用方不传也不会坏(默认空串,那几条自动不触发)。
    """
    out = []
    for fn in CHECKS:
        try:
            v = (fn(text or "", calls or [], prompt or "")
                 if "prompt" in fn.__code__.co_varnames[:fn.__code__.co_argcount]
                 else fn(text or "", calls or []))
        except Exception as e: v = f"体检项 {fn.__name__} 自己出错了:{type(e).__name__}: {e}"
        if v: out.append(dict(check=fn.__name__, msg=v))
    return out


# ── 接到 SDK 的 hook 上 ──────────────────────────────────────────────────
SCOPE_WORDS = ("整幅", "满地", "通身", "全身", "满绣", "整件")


def _write_tools():
    """会改数据的工具清单 —— **从 api.WRITE_TOOLS 取,不在这儿抄一份**。

    抄一份的下场刚发生过两次:加了 dispatch_batch,一处跟上了另一处没跟上,
    而**不跟上不会报错**,只是那一处从此当它是只读工具。
    取不到时退回一个保守的硬编码 —— 宁可多拦,不可漏拦。
    """
    try:
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
        import api as _api
        return tuple(_api.WRITE_TOOLS)
    except Exception:
        return ("assign_task", "dispatch_task", "reassign_task", "finish_task",
                "assign_batch", "dispatch_batch")


def _arg_key(tool, args):
    """给一次工具调用算个指纹 —— 用来认出「一模一样的参数又试了一次」。"""
    import hashlib
    payload = json.dumps({k: v for k, v in sorted((args or {}).items())},
                         ensure_ascii=False, sort_keys=True, default=str)
    return tool + ":" + hashlib.sha256(payload.encode()).hexdigest()[:16]


# 「这一句要安排的不止一件事」—— **确定性打标,只认少数高置信的说法**。
# 判据宁可漏,不可宽:判宽了天天拦正常的单条派活,人会学会无视这条提示;
# 而**被无视的闸和没有闸是一回事**。
_COMPOUND = re.compile(
    r"(这[几三四五六七八两]条|那[几三四五六七八两]条|[三四五六七八两]条都|"
    r"都派|全部派|挨个派|一个个派|每个人都|每人都|每天(都)?(安排|排)|"
    r"排[一整]?(周|下周|本周|这周)的?班|一周的班|排下周|批量)")


def _looks_compound(prompt):
    return bool(_COMPOUND.search(prompt or ""))


# ── 写之前必须先读哪个工具(集中一张表,代码照表判)──────────────────────
#
# 原来这几条前置要求散在下面各自的 if 里,**点名的是工具的旧名字**:
# 2026-09-19 工具 60→54 合并时,dispatch_pool / member_level / piece_ratios 并进了
# get_tasks / get_member / pattern_queue,而这里没跟着改 —— 于是批量分派、提等级积分、
# 改裁片占比这三个写工具的前置条件**永远满足不了**,它们一次都调不成(2026-09-22 能力盘点实测)。
# gate_test 当时没红:它核对的是代码里的实现清单,不是模型真能调的工具。
#
# 现在集中在这张表里,`gate_test` 逐个验「表里点名的工具必须在架上」——
# 以后再合并工具,漏改的名字当场红,不会再静默锁死一个写口。
先读 = {
    "assign_batch":    ("week_grid",),              # 排班前先看整周格子
    "dispatch_batch":  ("get_tasks",),              # 分派前先看待分配池(原 dispatch_pool,已并进 get_tasks)
    "assign_task":     ("task_types",),             # 派任务前先看类型规范
    "decide_approval": ("approval_queue",),         # 批之前先看这张单
    "apply_adjust":    ("get_member", "points_ledger"),  # 提等级/积分调整前先看现状(原 member_level)
    "set_piece_ratio": ("pattern_queue",),          # 改占比前先看这一片(原 piece_ratios)
}


def _读了(short, 读过):
    return any(n in 读过 for n in 先读.get(short, ()))


def pre_tool_verdict(name, args, prompt="", state_reads=None, state_writes=None):
    """PreToolUse 的判定逻辑,**纯函数版**。返回拦截理由,None = 放行。

    抽出来的理由:**安全边界必须离线可测**。
    藏在 async hook 里的判定,只能靠真跑一次模型才验得到 ——
    那样太贵、太慢,于是实际上就没人验,边界又退回成「但愿它是对的」。
    backend/boundary_audit.py 直接攻击这个函数。

    state_reads / state_writes:这一轮已经调过的工具名。写工具的闸要看它们 ——
    「一次只做一件」和「没查就别派」都是**跨调用**的判断,
    只看当前这一次的参数是判不出来的。
    """
    args = args or {}
    # ── 第一条:非 MCP 工具一律拦下 ────────────────────────────────────
    # sdk.py 的 disallowed_tools 是配置层的第一道,但**配置能被删掉、能被改错**,
    # 而这条保证太硬了,不能只靠一处配置守着。
    #
    # ⚠️ 这条注释原来写的是「工具全部只读、0 个写接口」——
    # 那句话在加了 assign_task / dispatch_task / finish_task 之后就**变成假的了**,
    # 而它在文件里躺着,看起来仍然像一条成立的保证。
    # **写下来但已经不对的约定,比没写更糟**:没写的话下一个人会去查,
    # 写着的话他会直接信。改保证的时候,记着回来改这句话。
    #
    # 现在的保证是:能写的只有那三个业务工具,它们各自从会话取身份、
    # 走和页面同一套权限判定;除此之外一个字都写不了(读写文件、执行命令、
    # 开子智能体一律拦在这一条)。
    #
    # 实跑抓到过:allowed_tools **不是排他白名单**,配上 bypassPermissions 之后
    # CLI 的内置工具(Bash / Write / Task …)照样在场,模型自己去开了 Bash。
    # 「模型没用」和「模型不能用」是两回事 —— 安全边界不能建在前者上。
    # ── 自家技能放行(2026-09-22,用户执行)──────────────────────────────
    # 这一条原来连 `Skill` 也一起拦了:35 次技能触发 33 次同一轮被拦下,
    # 报价 / 工期救援 / 换货等**自家技能的正文从来没加载过**,而技能评测只看模型「想不想调」,
    # 所以一直没人发现。放行**只限 skills_own.OURS**:第三方技能照旧拦 ——
    # 它们和汉服门店无关,放进来就是给模型多余的选择。
    if name == "Skill":
        _sk = str((args or {}).get("skill") or (args or {}).get("command") or "").strip().lstrip("/")
        try:
            from skills_own import OURS as _OURS
        except Exception:
            _OURS = ()
        if _sk in _OURS:
            return None
        return (f"技能「{_sk or '?'}」不是本系统自家的技能,已拦下。"
                f"能用的只有:{'、'.join(_OURS)}。")
    if name and not name.startswith("mcp__"):
        return (f"工具「{name}」不在本系统挂载的 MCP 工具里,已拦下。"
                "这个助手**只能用挂载的只读业务工具**,不能读写文件、"
                "不能执行命令、不能开子智能体。请改用 MCP 工具完成。")
    # ── 第一条半:写工具的闸 ──────────────────────────────────────────
    # 提示词里那条「一次只做一件、别换个参数重试」只是祈使句。
    # **hook 才是强制。** 这几条挡的都是实际会发生的事:
    #
    #   ① 一轮里连着写好几次 —— 用户说「把这三条都派了」,模型连开三刀,
    #      其中一刀参数猜错,而三条都已经落库了。
    #   ② 同一个动作重试 —— 工具报错,模型换个参数再试;
    #      **某一次可能碰巧成功**,那就是一条没人打算派的任务。
    #   ③ 没查就派 —— 不知道有哪些类型、不知道能派给谁,就先派了。
    #      派出去的东西看起来和正常任务一模一样。
    WRITE = _write_tools()
    short = name.rsplit("__", 1)[-1]
    if short in WRITE:
        # ── 尝试台账:**「改正参数重试」和「已经做成了还想再做一件」不是一回事** ──
        # 上一版把这两件揉成一条闸,后果是:参数写错被工具拒了之后,
        # 模型连改正的机会都没有 —— 而改正一个校验错误是完全正当的。
        # 抄 Accio 的 skill-executor-attempt-ledger:记每次尝试和它的结果,
        # 按**尝试的性质**分别处理。
        ledger = state_writes or []          # [{tool, key, ok}]
        succeeded = [x for x in ledger if isinstance(x, dict) and x.get("ok")]
        tried = [x for x in ledger if isinstance(x, dict)]
        key = _arg_key(short, args)

        if succeeded:
            done = succeeded[-1]["tool"]
            return (f"这一轮已经写成功一次了({done})。"
                    "**一次只做一件** —— 请先把这一条的结果告诉用户,"
                    "等他确认下一条再动手。连着写好几条,"
                    "其中一条参数猜错的话,几条都已经落库了。")

        same = [x for x in tried if x.get("key") == key]
        if same:
            return ("**一模一样的参数再试一次不会有不同结果。**"
                    f"上一次 {same[-1].get('tool')} 就是这些参数,被拒了。"
                    "把工具说的原因告诉用户,让他决定改什么。")
        if len(tried) >= 3:
            return (f"这一轮已经试了 {len(tried)} 次都没成。**别再猜了** —— "
                    "把最后一次的错误原话告诉用户。反复重试会在台账上留下一串失败记录,"
                    "而其中某一次可能碰巧成功了 —— 那就是一条没人打算派的任务。")

        # ── 计划先行:复合请求不许一条一条派 ──────────────────────────
        # 抄 Accio 的 intent-plan-required。它的实测发现是:
        # 「线上多意图问题样本里,绝大多数根本没进入 plan —— 不是因为请求不复杂,
        #   而是模型把它当成一个大 workflow 顺着执行了」。
        # 提示词里写「一次只做一件」召回不足,**hook 才是强制**。
        if short in ("assign_task", "dispatch_task") and _looks_compound(prompt):
            # **指对路。** 上一版不管什么动作都让改用 assign_batch,
            # 而 assign_batch 是新建任务的,派不了待分配池里已存在的单 ——
            # 影子埋点抓到过:模型被拦之后两条路都走不成,直接放弃了。
            # **拦一个动作的时候,得确认自己指的那条路真的通。**
            better = "assign_batch" if short == "assign_task" else "dispatch_batch"
            what = "一次排完" if short == "assign_task" else "一次分派完"
            return (f"用户这一句要安排的**不止一件事**,而你在一条一条做。"
                    f"一条一条做的问题是:前几条会成功,某一条才发现和前面撞了 —— "
                    f"而前几条已经落库了。**请改用 `{better}` {what}**:"
                    f"它全过才写、一条不过整批不写,而且能看见一条一条做看不见的冲突"
                    f"(同一个人被排了两个重叠时段)。")

        # **排班前必须先看格子。** 这条原来只写在 Skill 正文里(祈使句)——
        # 而 Accio 的实测结论是这类约束「召回不足」:模型会把它当成一个大流程顺着执行。
        # 不看现有占用就排,排出来的东西和正常任务长得一模一样,
        # 直到那天两个人同时约在一个时段。
        读过 = " ".join(x if isinstance(x, str) else "" for x in (state_reads or []))
        if short == "assign_batch" and not _读了(short, 读过):
            return ("排班之前先调 `week_grid()` 看现有占用 —— "
                    "**不看就排,排出来的东西和正常任务长得一模一样**,"
                    "直到那天两个人同时约在一个时段。"
                    "它还会告诉你哪几天完全没人排班,那一项不看整周摊开是发现不了的。")
        if short == "dispatch_batch" and not _读了(short, 读过):
            return ("批量分派之前先调 `get_tasks` 看**待分配池** —— "
                    "**你得先知道池子里有哪些、系统建议派给谁**,"
                    "否则你分派的依据是自己猜的,而猜出来的负责人和真的在库里长得一样。")

        if short == "assign_task" and not _读了(short, 读过):
            return ("派任务之前先调 `task_types()` 看类型规范 —— "
                    "类型决定挂哪张单据、完成时要不要传图。**没查就派**,"
                    "派出去的东西和正常任务长得一模一样,错了也看不出来。")

        # ── 审批那两个写工具的闸 ──────────────────────────────────
        # 这两条是**能力管理扫出来的**:`capman.py` 的探针发现
        # `apply_adjust` / `decide_approval` 在 guards.py 里一次都没被提到。
        # 通用闸(尝试台账、一次只做一件)覆盖得到它们,
        # **但「先看再做」这类工具专属的约束一条都没有** ——
        # 而这两个动作恰恰最怕盲做。
        if short == "decide_approval" and not _读了(short, 读过):
            return ("批之前先调 `approval_queue()` 把这张单看一遍 —— "
                    "**批一张没看过的单就是盲批**。批注写「同意」很容易,"
                    "而出事之后要查的正是「当时看了什么」;"
                    "什么都没看的话,那条批注是编的。")
        if short == "apply_adjust" and args.get("kind") in ("等级调整", "积分调整") \
                and not _读了(short, 读过):
            return (f"给客户提「{args.get('kind')}」之前,先调 `get_member()` "
                    f"或 `points_ledger()` 看他现在是什么状况 —— "
                    f"**不看现状就提调整,理由只能是编的**。"
                    f"而且很多时候一查就发现不用调:门槛是**滚动 12 个月**,"
                    f"按累计算会多算一批人。")

        # ── 版师核料那个写工具的闸 ────────────────────────────────
        # `set_piece_ratio` 改的是**排料的依据**:占比乘整件用料就是备多少布。
        # 两条工具专属的约束,通用闸都覆盖不到:
        #
        #   ① **没看过就改** —— 你不知道被覆盖的那个数是估算还是版师核过的。
        #      覆盖掉一个人核过的数,和改错一个估算值,不是一回事,
        #      而在库里它们长得一模一样(都只是一个小数)。
        #   ② **没写理由不许改** —— 工具那边也拒,这里再拦一道:
        #      工具拒了模型会**换个参数重试**,而重试三次里有一次碰巧带上理由,
        #      那条理由就是为了过校验编的。拦在调用之前,模型只能回去问版师。
        if short == "set_piece_ratio" and not _读了(short, 读过):
            return ("改占比之前先调 `pattern_queue(pattern=...)` 看这一片现在是多少、"
                    "来源是什么 —— **没看就改,等于拿一个数覆盖另一个数,"
                    "而你不知道被覆盖的那个是机器估的还是版师核过的**。"
                    "顺带也能看到折合米数,版师判断的是米数不是百分比。")
        if short == "set_piece_ratio" and not str(args.get("why") or "").strip():
            return ("`why` 没填。**这个数会被存进库,连同是谁核的、什么时候核的** —— "
                    "三个月后有人问「这一片为什么是这个数」,答得上来的是那行理由。"
                    "别自己替版师编一个理由:回去问他是量的、照排料图算的、"
                    "还是比着老版定的。")

        # ── 白坯试衣那两个写工具的闸(业务 09-22)──────────────────────
        # `record_fitting` 最怕的是**默认「签了」**:签字是责任转移点,
        # 记成签了而客户没签,门店出争议时拿着一张不存在的底牌。
        # 工具那边 signed 缺省是 False,模型不传就记成「没签」—— 那也不行:
        # 用户可能说过签了,模型漏传,台账上就少了一张真的底牌。**签没签必须明说。**
        if short == "record_fitting" and "signed" not in args:
            return ("`signed` 没给 —— **客户签没签字必须明说,不许默认**。"
                    "签字是责任转移点:默认「没签」会让一张真签过的单开不了裁,"
                    "默认「签了」会给门店一张不存在的底牌。回去问清楚再登记。")
        if short == "record_fitting" and args.get("round") in (None, "") \
                and not str(args.get("adjust") or "").strip():
            return ("新登记一轮试衣要写 `adjust`(改了哪几处,没改写「无需调整」)—— "
                    "只写「试了」的记录,出尺寸争议时说不清客户认可的是哪一版。"
                    "别替顾问编:回去问这一轮改了什么。")
        # `record_measure`:三个量体条件(内搭 / 鞋 / 呼吸)**必须明说** —— 缺一件等于没量,
        # 而模型最容易的做法是替顾问填一个「薄 / 赤足 / 平静呼气」。拦在调用之前,让它回去问。
        # 下单:确认之后就算已付款、进审核 —— 不许让工具去猜是哪一单;开单每一件都要指明给谁做
        if short == "confirm_order" and not str(args.get("order_id") or "").strip():
            return "确认下单要给订单号 —— 确认之后就算已付款、进审核,不许让工具去猜是哪一单。先跟用户确认单号。"
        if short == "open_order" and any(not str((x or {}).get("wearer_id") or "").strip()
                                         for x in (args.get("items") or [{}])):
            return ("开单时每一件都要指明给谁做(wearer_id)—— 下单量体量的必须是穿这件的人。"
                    "回去问用户这件是给谁做的,**不要自己挑一个着装人**。")
        if short == "record_measure" and not all(str(args.get(k) or "").strip()
                                                  for k in ("inner", "shoe", "breath")):
            return ("量体的三个条件(内搭 / 鞋 / 呼吸)**要问清楚,不许默认** —— "
                    "同一个人穿厚内搭和不穿,胸围差 3–4cm;没记条件的尺寸,返修时判断不了是量错了还是穿法变了。")
        # `verify_fit_code`:码**只能是用户这句话里说出来的** —— 模型最容易的做法是编一个 6 位数
        #  「先试试」,而输错会记次数、5 次作废,编一次就烧掉顾客一次机会。数字对不上用户原话就拦。
        if short == "verify_fit_code":
            _码 = "".join(ch for ch in str(args.get("code") or "") if ch.isdigit())
            _说 = "".join(ch for ch in str(prompt or "") if ch.isdigit())
            if not _码 or _码 not in _说:
                return ("试穿合身码**只能是顾客给的、用户说出来的那一个** —— 用户这句话里没有这串数字。"
                        "别编、别猜:回去问用户顾客给的 6 位码是多少。")
        # `verify_repair_return`:同交付签收 —— 码只能是用户这句话里说出来的
        if short == "verify_repair_return":
            _码 = "".join(ch for ch in str(args.get("code") or "") if ch.isdigit())
            _说 = "".join(ch for ch in str(prompt or "") if ch.isdigit())
            if not _码 or _码 not in _说:
                return ("返修件签收的码**只能是顾客给的、用户说出来的那一个** —— 用户这句话里没有这串数字。"
                        "回去问用户顾客给的 6 位码是多少。")
        # `decide_repair`:谁承担、返修还是重做**只能照用户说的填** —— 模型最容易的做法是按判责建议替店长定
        if short == "decide_repair":
            _p = str(prompt or "")
            if str(args.get("plan") or "") not in _p:
                return (f"返修还是重做要**店长说**(业务 09-22)—— 用户这句话里没说「{args.get('plan')}」。"
                        "别按建议替店长定,回去问。")
            if not any(w in _p for w in ("顾客", "客户", "企业", "我们", "门店", "公司", "店里")):
                return "谁承担要**店长说**(顾客 / 企业)—— 用户这句话里没说。别按判责建议替店长定,回去问。"
            if args.get("customer_agreed") and not str(args.get("agree_note") or "").strip():
                return "记「顾客同意付费」要写凭据(比如「顾客电话同意 300 元」)—— 回去问用户顾客是怎么同意的。"
        # `ratify_complete`:追认要写理由 —— 没有理由的追认等于替顾客点了完成
        if short == "ratify_complete" and not str(args.get("reason") or "").strip():
            return "追认完成要写理由(比如「已电话联系,顾客表示没问题」)—— 回去问用户联系过顾客没有。"
        # `record_pickup` 转寄:**物流单号只能是用户说出来的那一个**(2026-09-24 评测抓到)。
        # 那一轮用户只说「顾客来不了,帮我转寄」,模型回答「已定为转寄,物流单号 SF2321616818」——
        # **号是它编的**。写口只管「转寄必须有单号」,编一个照样能过;而寄丢了按这个号查,查无此单。
        # 和试穿合身码那条是同一个形状:**凭据类的值不许模型生成**。
        if short == "record_pickup" and str(args.get("action") or "") == "取件方式" \
                and str(args.get("mode") or "") == "转寄":
            _号 = "".join(ch for ch in str(args.get("tracking_no") or "") if ch.isalnum()).upper()
            _说 = "".join(ch for ch in str(prompt or "") if ch.isalnum()).upper()
            if not _号 or _号 not in _说:
                return ("转寄的物流单号**只能照抄用户给的那一个** —— 用户这句话里没有这个单号。"
                        "别编、别猜:回去问他快递单号是多少,没单号就先别改成转寄。")
        # `record_pickup` 不合身:要写清哪里不合身 —— 返修和判责都看这一句
        if short == "record_pickup" and str(args.get("action") or "") == "不合身" \
                and not str(args.get("issue") or "").strip():
            return "登记不合身要写清哪里不合身(比如「腰围紧 2cm」)—— 回去问用户。"
        # `start_cutting` 被 MUSLIN_GATE 拒过之后,通用闸已经不许同参数重试;
        # 这里再挡一种:**没给单号就开裁**(开裁不可逆,不许让工具去猜是哪一单)。
        if short == "start_cutting" and not str(args.get("order_id") or "").strip():
            return ("开裁要给订单号 —— **开裁不可逆**,不许让工具去猜是哪一单。"
                    "先跟版师确认单号。")

    # ── 第二条:拿客户号当着装人编号 ──────────────────────────────────
    if name.endswith(("plan_for_event", "forecast_growth", "get_wearer")):
        w = args.get("wearer_id") or ""
        if w.startswith("C"):
            return (f"「{w}」是客户号(账号),不是着装人编号。"
                    "**账号和衣服穿在谁身上是两回事** —— "
                    "先用 get_wearer(customer=...) 找到那个人,再拿 W 开头的编号来调。")
    # ── 第三条:场景倒推的日期体检 ────────────────────────────────────
    if name.endswith("plan_for_event"):
        d = args.get("event_date") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return (f"event_date「{d}」不是 YYYY-MM-DD。"
                    "客户说「明年六月」时要先换算成具体日期再调。")
        # 「将来」按业务上的今天算(同上面注入的那句;机器的今天比演示世界晚,会把 9-10 的婚期当成过去拦掉)
        if d <= (_业务今天() or dt.date.today().isoformat()):
            return (f"用件日期 {d} 不在将来。倒推是往前排产,"
                    "过去的日子推不出窗口 —— 跟客户确认是哪一年。")
    # ── 第四条:客户说了「整幅」而工具传「局部」 ──────────────────────
    # 整幅按局部的 4 倍算,成本和工期都会差一大截,一旦发生就是报价事故
    if name.endswith(("kb_bom", "kb_lead")) and args.get("scope", "局部") == "局部":
        hit = [w for w in SCOPE_WORDS if w in (prompt or "")]
        if hit:
            return (f"用户说的是「{hit[0]}」,你传的 scope 是「局部」——"
                    "整幅按局部的 4 倍算,成本和工期都会差一大截。"
                    "改成 scope=\"整幅\" 重新调一次。")
    return None


# 按号取单条的工具 → (那个号的参数名, 人话叫法)。
# **只列「给了号就一定是单条」的那几个** —— 参数名本身就是判据,
# 不必去猜返回结构;返回结构会随功能改,参数名不会。
_锚点键 = {
    "get_order":    ("order_id",    "订单号"),
    "get_maintain": ("maintain_id", "维保单号"),
    "get_wearer":   ("wearer_id",   "着装人号"),
    "get_tasks":    ("task_id",     "任务号"),
    "get_aftersale": ("order_id",   "售后关联订单号"),
}


# ── 每轮往模型上下文里塞什么,以及**每一段管的是哪件事** ────────────────
# 为什么要登记:2026-09-22 那次「晚 3 天说成晚 25 天」——
# 规矩(TL53)说「业务上的今天是 8-31」,而这里每轮注入「今天是〈机器日期〉,一律以这一天为准」。
# **两处管同一件事,而谁也不知道另一处存在**;又因为注入贴着用户消息、还是命令口气,它赢了。
# 登记之后,tools/context_conflict_check.py 机械地查「这件事有几个人在说」——
# 它不懂语义,也不需要懂:**「有两个人在说」本身就是要人来裁的信号。**
注入登记 = {
    "业务今天":   ("日期",),          # 权威在这里:规矩 TL53 只是复述,改这里必须同时改它
    "工作日记":   (),                 # 只给背景,不定口径
    "当前方案":   ("方案归属",),      # 这一轮说的是哪一份方案
    "压缩提醒":   ("单据号",),        # 压缩后把按号取过的单据注回去
}


def make_hooks(state):
    """state 是一个 dict,跨 hook 共享这一轮的上下文。"""

    async def on_prompt(inp, tool_use_id, ctx):
        # 模型不知道今天几号 —— 工期倒推会算错,而且错得很自然,没人看得出来
        # ⚠️ **注入的是业务上的今天(seed.TODAY),不是机器的今天。** 原来这里是 dt.date.today(),
        # 而演示世界的今天是 8-31、机器是 9-22 —— 这一句每轮都命令模型「以 9-22 为准」,
        # 正好和规矩 TL53 打架:工厂回传评测里逾期 3 天被说成 25 天(2026-09-22 查实)。
        # 日期和 TL53 取自同一个源头(prompts._TODAY ← seed.TODAY),不另写一份。
        # CLI 自己还会附一句「Today's date is <机器日期>」,关不掉 —— 所以这里要**明说**那个是机器的日期。
        state["prompt"] = inp.get("prompt", "")
        state["calls"] = []
        _今 = _业务今天()
        # 登记:业务今天
        ctx_add = (f"[系统注入] 业务上的今天是 {_今}。运行环境里显示的日期是机器的日期,**不是这家店的今天**;"
                   "涉及日期的推算一律以业务上的今天为准,工具返回里算好的天数照着说。"
                   if _今 else
                   "[系统注入] 涉及日期的推算以工具返回里算好的为准;运行环境里显示的日期是机器的日期,不是这家店的今天。")
        # **每一轮都把日记塞进来(三条)。** 日记建起来之后有一阵只有写没有读,
        # 而没人读的日记和没有日记是一回事。
        # 原本想只在「重要动作」时注,判据当场就漏(「排下周的班」不含「排班」)——
        # **判据漏一次的代价比每轮多几百 token 大得多**,而且失灵是静默的。
        try:
            import diary as _dy
            b = _dy.brief(3)
            if b:
                ctx_add += "\n\n" + b        # 登记:工作日记
                state["_diary_read"] = True
        except Exception:
            pass
        # **当前在谈的是哪一份方案。** 这是「一件事」那条线的落点:
        # 方案号放在 harness 留给我们的 `state` 里,**不放在对话文本里**。
        #
        # 为什么不靠模型自己记:自动压缩压的是「读起来连贯」,不是「标识不丢」。
        # 压完之后模型很可能仍然记得「在聊一套唐制襦裙」,却**丢掉了 SC2601 这个号** ——
        # 而这两种状态在对话里长得一模一样,直到它按错误的方案下了单。
        当 = state.get("当前方案")
        if 当:
            # 登记:当前方案
            ctx_add += (f"\n\n[系统注入] 本次会话里已经明确取过一份方案:"
                       f"**{当['号']}**({当.get('名称')} · {当.get('状态')})。"
                       f"客户说「这个 / 刚才那套 / 就按这个」时,**默认指的是它**,"
                       f"但推进前仍要把号说出来让人确认。"
                       f"⚠️ 若客户提到的是别的方案,以客户说的为准,并重新查一次。")
        # ── 刚被压缩过的那一轮,把锚点注回去 ─────────────────────
        # **压缩是模型察觉不到的** —— 摘要读起来完整、自洽、没有窟窿,
        # 所以它不会自己想起来「我是不是丢了个单号」。
        # 只在压缩后的第一轮注:注完这些号就又在对话里了,每轮重注是白花 token。
        if state.pop("刚压缩过", None):
            锚 = state.get("锚点") or {}
            # 登记:压缩提醒
            ctx_add += ("\n\n[系统注入] ⚠️ **这轮对话刚被压缩过。**"
                        "压缩保的是「读起来连贯」,不保「标识不丢」——"
                        "**没有编号、却决定下一步的事实**(客户说过不要撞色、"
                        "预算上限、哪天要穿)很可能已经不在了。"
                        "推进任何写动作之前,把关键前提跟人再确认一遍。")
            if 锚:
                ctx_add += ("\n压缩前**按号取过**的单据:"
                            + "、".join(f"{k} {v}" for k, v in 锚.items())
                            + " —— 这些号以它们为准,不要凭记忆重写。")
        return {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ctx_add}}

    async def pre_tool(inp, tool_use_id, ctx):
        name, args = inp.get("tool_name", ""), inp.get("tool_input") or {}
        called = [c["tool"] for c in (state.get("calls") or [])]
        v = pre_tool_verdict(name, args, state.get("prompt", ""),
                             state_reads=called, state_writes=state.get("wrote") or [])
        if v:
            if not name.startswith("mcp__"):
                state.setdefault("blocked_tools", []).append(name)
            # 影子埋点:**只记不改** —— 记完照样按原来的判定返回。
            # 这一层要是能影响返回值,它就不是观测了。
            try:
                import funnel as _fn
                state.setdefault("_funnel_blocks", []).append(v)
                _fn.event(state, "blocked", tool=name.rsplit("__", 1)[-1], reason=v[:80])
            except Exception:
                pass
            return {"decision": "block", "reason": v}
        # 放行的写工具记一笔**结构化的**:哪个工具、什么参数、成没成。
        # 只记工具名的话,分不出「改正参数重试」和「又要做一件新的」——
        # 而这两件的处理方式完全不同(前者该放,后者该拦)。
        short2 = name.rsplit("__", 1)[-1]
        if short2 in ("assign_task", "dispatch_task", "reassign_task",
                      "finish_task", "assign_batch"):
            state.setdefault("wrote", []).append(
                dict(tool=short2, key=_arg_key(short2, args), ok=None))
        return {}

    async def post_tool(inp, tool_use_id, ctx):
        # **回填这次写成没成。** 被工具拒了的不算「做完一件」——
        # 不回填的话,一次校验失败就把这一轮的写额度用光了,
        # 而改正一个校验错误是完全正当的。
        _n2 = (inp.get("tool_name") or "").rsplit("__", 1)[-1]
        _w = state.get("wrote") or []
        if _w and _w[-1].get("tool") == _n2 and _w[-1].get("ok") is None:
            _r = _unwrap(inp.get("tool_response"))
            _w[-1]["ok"] = bool(isinstance(_r, dict) and _r.get("ok"))
        _out = _unwrap(inp.get("tool_response"))
        state.setdefault("calls", []).append(dict(
            tool=inp.get("tool_name", ""), input=inp.get("tool_input"),
            output=_out))

        # ── 记住「当前方案」 ──────────────────────────────────────
        # ⚠️ **只有按方案号取过单条时才记,列清单不算。**
        #
        # 这条限制是刻意的:业务 2026-09-18 定了「一个客户可以多条方案同时锁定」,
        # 所以「锁定那条」不是唯一标识。如果列了一遍清单就顺手把第一条当成
        # 「当前方案」,等于**把刚刚堵死的那条消歧捷径从后门放回来** ——
        # 而且是以一种更隐蔽的方式:模型没挑,是 hook 替它挑的。
        if _n2 == "get_scheme" and isinstance(_out, dict) and _out.get("方案号"):
            state["当前方案"] = {"号": _out["方案号"], "名称": _out.get("名称"),
                              "状态": _out.get("状态"), "客户号": _out.get("客户号")}

        # ── 记住这一轮**按号取过**的其它单据(锚点) ────────────────
        # 方案号有专门的一格,但顾问一轮里还会按号取订单、维保单、着装人、任务 ——
        # **这些号同样没有第二个地方存,一旦被压缩吃掉就只能靠模型记**。
        #
        # 判据和方案号那条**一字不差**:只有**给了那个号**的调用才算。
        # 按客户列一串订单不算 —— 列清单里挑一条,是 hook 替模型挑,
        # 而 hook 不出现在对话里,没人看得见它挑过。
        k, 叫法 = _锚点键.get(_n2, (None, None))
        if k:
            v = (inp.get("tool_input") or {}).get(k)
            if v:
                state.setdefault("锚点", {})[叫法] = v
        return {}

    async def on_stop(inp, tool_use_id, ctx):
        if state.get("stopped"):     # 已经打回过一次,不再无限循环
            return {}
        text = _last_answer(inp.get("transcript_path"))
        bad = check_answer(text, state.get("calls"), state.get("prompt"))
        if not bad: return {}
        state["stopped"] = True
        state["violations"] = bad
        return {"decision": "block",
                "reason": "交付前体检没过,请修正后重答:\n"
                          + "\n".join(f"· {b['msg']}" for b in bad)}

    async def on_compact(inp, tool_use_id, ctx):
        """压缩前。**这是唯一知道「压缩发生过」的地方** ——
        压缩之后的模型读不出自己被压过,摘要看起来什么都不缺。

        这里不做判断,只立一个旗:下一轮 on_prompt 看见它,
        把锚点和那句警告注回去。判断留给模型,旗留给 hook ——
        **hook 替模型做的判断不出现在对话里,没人看得见它做过。**
        """
        state["刚压缩过"] = True
        state["压缩次数"] = state.get("压缩次数", 0) + 1
        return {}

    from claude_agent_sdk import HookMatcher
    return {
        "UserPromptSubmit": [HookMatcher(hooks=[on_prompt])],
        "PreToolUse":       [HookMatcher(hooks=[pre_tool])],
        "PostToolUse":      [HookMatcher(hooks=[post_tool])],
        "Stop":             [HookMatcher(hooks=[on_stop])],
        "PreCompact":       [HookMatcher(hooks=[on_compact])],
    }


def _unwrap(resp):
    """MCP 工具的返回被包在 content[0].text 里,拆出来才好检查"""
    if isinstance(resp, dict):
        cont = resp.get("content")
        if isinstance(cont, list) and cont and isinstance(cont[0], dict):
            t = cont[0].get("text")
            if t:
                try: return json.loads(t)
                except Exception: return t
        return resp
    return resp


def _last_answer(path):
    """从 transcript 里取最后一条助手文本。Stop hook 的入参里没有答案正文,
    只有 transcript_path —— 读文件是唯一拿得到的办法。"""
    if not path or not os.path.exists(path): return ""
    out = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try: m = json.loads(line)
        except Exception: continue
        msg = m.get("message") or {}
        if m.get("type") == "assistant" and isinstance(msg.get("content"), list):
            txt = "".join(b.get("text", "") for b in msg["content"]
                          if isinstance(b, dict) and b.get("type") == "text")
            if txt.strip(): out = [txt]
        elif m.get("type") == "user":
            out = []          # 新一轮开始,清掉上一轮的答案
    return out[0] if out else ""
