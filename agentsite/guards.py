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
# 整单结论的信号词 —— 只有给总量时才要求调过对应的算账工具
TOTAL_D  = ("整单", "总共", "一共", "交期", "工期", "多久", "大概要", "预计", "能拿到", "交付")
TOTAL_M  = ("总价", "合计", "报价", "价格", "多少钱", "售价", "要花")
PRICEY   = ("售价", "报价", "价格", "多少钱", "卖", "要花", "收")
HEDGE    = ("物料成本", "不含", "不是售价", "不是报价", "仅物料", "材料成本")
UNKNOWN  = ("查不到", "未录入", "没有录入", "尚未录入", "转工艺负责人", "未定义", "不清楚")
# 中文否定与子串**统一走 agent/textmatch.py** —— 原来四个文件各有一份词表,
# 每次踩坑只补一份,别的三份继续错。这里只留业务词表。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import textmatch as tm      # noqa: E402
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


def _called(calls, name):
    return [c for c in calls if c.get("tool", "").endswith(name)]


def _res(c):
    r = c.get("output")
    if isinstance(r, str):
        try: r = json.loads(r)
        except Exception: return {}
    return r if isinstance(r, dict) else {}


# ── 体检项 ──────────────────────────────────────────────────────────────
def g1_no_source(text, calls):
    """给了数字结论,却没查过 —— **「该查的没查就答」是工具变多之后最高频的失败**,
    而它恰恰是评测集最难覆盖的:答案看起来完全正常,只是那个数字是编的。"""
    monies, days = _monies(text), _days(text)
    if not (monies or days): return None
    if not calls:
        return "答案里给了具体数字,但这一轮**一个工具都没调** —— 数字没有出处,不能这么答"
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


CHECKS = [g1_no_source, g2_cost_as_price, g3_lead_single, g4_no_rule,
          g5_fit_guess, g6_undefined, g7_rush_promise, g8_business_fact, g9_quote_disclaimer,
          g10_point_no_range, g11_girth_point, g12_expired_ignored, g13_target_conflict, g14_consent_bypass,
          g15_growth_plan_sections, g16_bypass_control,
          g17_liability_promise, g18_vision_conclusion,
          g19_account_state, g20_consent_version]


def check_answer(text, calls):
    """返回违规清单。空清单 = 通过。纯函数,可离线测。"""
    out = []
    for fn in CHECKS:
        try: v = fn(text or "", calls or [])
        except Exception as e: v = f"体检项 {fn.__name__} 自己出错了:{type(e).__name__}: {e}"
        if v: out.append(dict(check=fn.__name__, msg=v))
    return out


# ── 接到 SDK 的 hook 上 ──────────────────────────────────────────────────
SCOPE_WORDS = ("整幅", "满地", "通身", "全身", "满绣", "整件")


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
    WRITE = ("assign_task", "dispatch_task", "reassign_task", "finish_task", "assign_batch")
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
            return ("用户这一句要安排的**不止一件事**,而你在一条一条派。"
                    "一条一条派的问题是:前几条会成功,某一条才发现和前面撞了 —— "
                    "而前几条已经落库了。**请改用 `assign_batch` 一次排完**:"
                    "它全过才写、一条不过整批不写,而且能看见一条一条派看不见的冲突"
                    "(同一个人被排了两个重叠时段)。")

        if short == "assign_task" and "task_types" not in " ".join(
                x if isinstance(x, str) else "" for x in (state_reads or [])):
            return ("派任务之前先调 `task_types()` 看类型规范 —— "
                    "类型决定挂哪张单据、完成时要不要传图。**没查就派**,"
                    "派出去的东西和正常任务长得一模一样,错了也看不出来。")

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
        if d <= dt.date.today().isoformat():
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


def make_hooks(state):
    """state 是一个 dict,跨 hook 共享这一轮的上下文。"""

    async def on_prompt(inp, tool_use_id, ctx):
        # 模型不知道今天几号 —— 工期倒推会算错,而且错得很自然,没人看得出来
        state["prompt"] = inp.get("prompt", "")
        state["calls"] = []
        return {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"[系统注入] 今天是 {dt.date.today().isoformat()}。"
                                 "涉及日期的推算一律以这一天为准,不要自己猜今天几号。"}}

    async def pre_tool(inp, tool_use_id, ctx):
        name, args = inp.get("tool_name", ""), inp.get("tool_input") or {}
        called = [c["tool"] for c in (state.get("calls") or [])]
        v = pre_tool_verdict(name, args, state.get("prompt", ""),
                             state_reads=called, state_writes=state.get("wrote") or [])
        if v:
            if not name.startswith("mcp__"):
                state.setdefault("blocked_tools", []).append(name)
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
        state.setdefault("calls", []).append(dict(
            tool=inp.get("tool_name", ""), input=inp.get("tool_input"),
            output=_unwrap(inp.get("tool_response"))))
        return {}

    async def on_stop(inp, tool_use_id, ctx):
        if state.get("stopped"):     # 已经打回过一次,不再无限循环
            return {}
        text = _last_answer(inp.get("transcript_path"))
        bad = check_answer(text, state.get("calls"))
        if not bad: return {}
        state["stopped"] = True
        state["violations"] = bad
        return {"decision": "block",
                "reason": "交付前体检没过,请修正后重答:\n"
                          + "\n".join(f"· {b['msg']}" for b in bad)}

    from claude_agent_sdk import HookMatcher
    return {
        "UserPromptSubmit": [HookMatcher(hooks=[on_prompt])],
        "PreToolUse":       [HookMatcher(hooks=[pre_tool])],
        "PostToolUse":      [HookMatcher(hooks=[post_tool])],
        "Stop":             [HookMatcher(hooks=[on_stop])],
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
