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
import datetime as dt, json, os, re

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
NEG      = ("不", "无法", "没法", "不能", "拒绝", "无", "别", "勿")
# 含「不」但**不表否定**的词。不排掉它们,「不过加钱可以赶出来」会被当成拒绝加急放行 ——
# 这正是判分器栽过四次的那类错的镜像:那次是把否定当肯定,这次是把转折当否定。
NEG_FALSE = ("不过", "不仅", "不但", "不只", "不光", "不妨", "差不多", "要不", "不然",
             "不如", "不用说", "无非", "无论")
# 判「不可」的说法 —— 答案里没有这类断言时,g4 不该开火
DENY = ("不可", "做不了", "不能做", "不行", "没法做", "做不出", "无法做", "做不到")


def _num(s):
    try: return float(str(s).replace(",", ""))
    except (TypeError, ValueError): return None


def _near(text, idx, words, span=28):
    """idx 附近 span 字内有没有 words 里的词"""
    seg = text[max(0, idx - span): idx + span]
    return any(w in seg for w in words)


def _negated(text, idx, span=12):
    """idx 前面 span 字内有没有真的否定词。

    判分器在否定上栽过四次(「不得重新发起退款」被当成「建议重新发起退款」),
    这里是它的镜像坑:**「不过」「不仅」这些含「不」但表转折的词会被误认成否定**,
    于是「不过加钱可以赶出来」就被当成拒绝加急放过去了。先把它们抹掉再看。
    """
    seg = text[max(0, idx - span): idx]
    for w in NEG_FALSE: seg = seg.replace(w, "〇")
    return any(w in seg for w in NEG)


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
        if m and not _negated(text, m.start()):
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
        if not _negated(text, m.start()):
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


CHECKS = [g1_no_source, g2_cost_as_price, g3_lead_single, g4_no_rule,
          g5_fit_guess, g6_undefined, g7_rush_promise, g8_business_fact]


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
        # 客户说了「整幅」而工具传「局部」—— 成本和工期差 4 倍,一旦发生就是报价事故
        if name.endswith(("kb_bom", "kb_lead")) and args.get("scope", "局部") == "局部":
            p = state.get("prompt", "")
            hit = [w for w in SCOPE_WORDS if w in p]
            if hit:
                return {"decision": "block",
                        "reason": f"用户说的是「{hit[0]}」,你传的 scope 是「局部」——"
                                  "整幅按局部的 4 倍算,成本和工期都会差一大截。"
                                  "改成 scope=\"整幅\" 重新调一次。"}
        return {}

    async def post_tool(inp, tool_use_id, ctx):
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
