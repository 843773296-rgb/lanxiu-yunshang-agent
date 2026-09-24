#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记录仪(树状版)—— 一次提问记成一棵 trace,每一步记成一个 span。

## 为什么要在 llm-trace.jsonl 之外再写一份

原来那份是**一次提问一行**:总 token、总花费、总耗时、调了几个工具。
它回答得了「今天花了多少钱」,回答不了调试真正要问的那三句:

    这一步的输入到底是什么      →  旧格式里没有
    这个工具返回了什么          →  旧格式里没有(只记了调用次数)
    钱花在哪一步上              →  旧格式只有总数,摊不到步

**所以不是把旧的改宽,是换一种形状**:树。
一次提问 = 一棵树,根是「这一轮」,下面挂每次模型调用,
模型调用下面挂它要的工具,子助手(Task)出来的调用挂在那个工具下面。

旧那份**不动、继续写** —— 它是横向对比一代/三代的历史数据,格式一换就断了。
两份各司其职:旧的管趋势,这份管一次运行看得清不清楚。

## 字段名照 OpenTelemetry 的 GenAI 语义约定,不自创

调试后台这件事业内已经有共识字段了(LangSmith / Langfuse / Phoenix / Braintrust
/ Datadog 都在往这套靠)。自创一套的代价不是难看,是**以后想换现成的看板要重洗一遍数据**。

    span 名        invoke_agent 门店顾问 / chat <模型> / execute_tool get_order
    操作类型       gen_ai.operation.name       invoke_agent | chat | execute_tool
    会话           gen_ai.conversation.id      SDK 的 session_id
    模型           gen_ai.request.model / gen_ai.response.model
    用量           gen_ai.usage.input_tokens / .output_tokens
    工具           gen_ai.tool.name / .call.id / .call.arguments / .call.result
    出错           error.type

两处**我们自己加的**,前缀 `lanxiu.` 和标准字段分开,免得日后分不清哪些是约定哪些是我们编的:

    lanxiu.cost_usd     按真实单价算的钱(SDK 自报那个按 Claude 单价算,虚高几十倍)
    lanxiu.guard.*      体检/拦截,这是这个项目独有的
    lanxiu.gen          哪一代架构(V1/V3)

缓存那两个(cache_read_input_tokens / cache_creation_input_tokens)**不是 OTel 的正式字段**,
是各家厂商的扩展,这里跟着 Anthropic 的叫法写,并在这里注明它不是约定的一部分。

## 时间是「消息到我们手上的时刻」

SDK 不给每条消息的服务端时间戳,所以 span 的起止是**我们收到它的时刻**。
网络和排队都算在里面。**要拿它判「模型慢还是网络慢」是不成立的** —— 说清楚,免得日后当成精确值用。

## 隐私:这份日志比旧那份敏感得多

旧记录仪**默认不记内容**,理由写在 trace.py 里:工具返回里带客户档案,
一旦进日志,日志就成了一份没人当敏感数据管的客户资料副本。

而这份的**全部价值就在于记内容** —— 不记参数和返回值,调试后台就是个空壳。
所以换成三道约束,而不是不记:

    ① 文件不进版本库(.gitignore),只在本机
    ② 凭据类字段名(密码/哈希/盐/token/密钥)**连键带值抹掉**,并留下抹过的痕迹
    ③ 有一条检查(agent/spans_check.py)扫这份文件,扫出凭据就红

⚠️ 第 ② 条抹的是**键名像凭据的**,不是「内容像密码的」。
靠猜内容必漏 —— 这个项目在中文词表上栽过七次,同一个教训。
真正的保险是第 ① 条和「凭据根本不经工具层」这条上游规矩。
"""
import json, os, re, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "..", ".feynman", "spans.jsonl")

# ── 咬合记录 ──────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。`--selftest` 里都验得到。
咬合 = [
    ("把凭据词表里的「密码」删掉", "凭据按键名抹掉(参数)"),
    ("把 token 写成光秃秃的(用量字段会被当成凭据)",
     "input_tokens / cache_read_input_tokens 不算凭据"),
    ("排树时把父找不到的 span 丢掉(页面上表现为「这一步没发生过」)",
     "父找不到的 span 不会被吃掉"),
    ("算账时把根的汇总和分步的值一起加(每个数都算两遍)",
     "有根汇总时以根为准,不和分步相加"),
    ("落盘时把没收尾的 span 当成正常结束", "没收尾的 span 标成「未收尾」"),
]

# 一个字段最多记多长。调试要的是「看得出是哪一单」,不是完整副本;
# 工具返回动辄几千字(比如整份工艺库),全记下来文件一天就上 G。
上限 = int(os.environ.get("SPANS_MAX_CHARS", "4000"))
轮转字节 = int(os.environ.get("SPANS_ROTATE_BYTES", str(64 * 1024 * 1024)))

# 凭据类键名。**只按键名抹,不猜内容。**
# ⚠️ `token` 那一项**不能写光秃秃的** —— 第一版就是,结果把
# `gen_ai.usage.input_tokens` / `cache_read_input_tokens` 全当成凭据报了红
# (2026-09-24 当场被自己的检查抓到)。**复数形式的 tokens 是用量计数,不是凭据。**
# 这正是这个项目在中文词表上栽过七次的同一个形状:词写宽了,红的全是好人。
凭据键 = re.compile(r"(密码|口令|盐值|哈希|凭据|password|passwd|pwd|salt|hash|"
                   r"secret|token(?!s)|api[_-]?key|apikey|authorization|credential)", re.I)
抹了 = "「凭据已抹」"


def _抹(x, 深=0):
    """按键名抹凭据。列表和字典递归,别的原样。"""
    if 深 > 12: return x
    if isinstance(x, dict):
        return {k: (抹了 if 凭据键.search(str(k)) else _抹(v, 深 + 1)) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_抹(v, 深 + 1) for v in x]
    return x


def _文本(x):
    """统一转成字符串存 —— OTel 里 tool.call.arguments/result 就是字符串。"""
    if x is None: return None
    if isinstance(x, str): return x
    try: return json.dumps(x, ensure_ascii=False, default=str)
    except Exception: return str(x)


def 装值(x):
    """抹 → 转字符串 → 截断。返回 (字符串, 截断了吗)。"""
    s = _文本(_抹(x))
    if s is None: return None, False
    if os.environ.get("SPANS_FULL") == "1" or len(s) <= 上限: return s, False
    return s[:上限] + f"…〔还有 {len(s)-上限} 字未记〕", True


class 一棵树:
    """一次提问的 trace。用法:开根 → 中间开/收若干 span → 落盘。

    **不在中途写文件。** 中途写的话,一次运行会散在文件里几十行中间,
    而运行是并发的(两个人同时用),读的时候要靠 trace_id 重新拼 —— 能拼,但没必要。
    一次运行几十个 span,攒在内存里几十 KB,结束时一次写完。
    """

    def __init__(self, *, 角色=None, 会话号=None, 模型=None, 供应商=None, gen="V3"):
        self.tid = uuid.uuid4().hex
        self.spans = []
        self.开始 = time.time()
        self.元 = dict(角色=角色, 会话号=会话号, 模型=模型, 供应商=供应商, gen=gen)

    # ── 开一个 span ────────────────────────────────────────────────
    def 开(self, 操作, 名, *, 父=None, 属性=None, sid=None, 起=None):
        """操作: invoke_agent / chat / execute_tool / 别的。返回 span_id。"""
        s = dict(trace_id=self.tid, span_id=sid or uuid.uuid4().hex[:16],
                 parent_span_id=父, name=名,
                 start=起 if 起 is not None else time.time(), end=None,
                 attr={"gen_ai.operation.name": 操作}, status="unset")
        if self.元.get("供应商"): s["attr"]["gen_ai.provider.name"] = self.元["供应商"]
        if 属性: s["attr"].update({k: v for k, v in 属性.items() if v is not None})
        self.spans.append(s)
        return s["span_id"]

    def 找(self, sid):
        return next((s for s in self.spans if s["span_id"] == sid), None)

    def 收(self, sid, *, 属性=None, 出错=None, 止=None):
        s = self.找(sid)
        if not s: return
        s["end"] = 止 if 止 is not None else time.time()
        if 属性: s["attr"].update({k: v for k, v in 属性.items() if v is not None})
        if 出错:
            s["status"] = "error"
            s["attr"]["error.type"] = str(出错)[:200]
        elif s["status"] == "unset":
            s["status"] = "ok"

    # ── 两种最常开的 span,给个顺手的写法 ───────────────────────────
    def 一次模型调用(self, *, 父, 模型, usage=None, 停因=None, 花费=None,
                     消息号=None, 起=None):
        u = usage or {}
        attr = {
            "gen_ai.request.model": self.元.get("模型"),
            "gen_ai.response.model": 模型,
            "gen_ai.response.id": 消息号,
            "gen_ai.usage.input_tokens": u.get("input_tokens"),
            "gen_ai.usage.output_tokens": u.get("output_tokens"),
            # ⚠️ 下面两个不是 OTel 约定字段,是厂商扩展(Anthropic 的叫法)
            "gen_ai.usage.cache_read_input_tokens": u.get("cache_read_input_tokens"),
            "gen_ai.usage.cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
            "gen_ai.response.finish_reasons": [停因] if 停因 else None,
            "lanxiu.cost_usd": 花费,
        }
        sid = self.开("chat", f"chat {模型 or self.元.get('模型') or '?'}",
                      父=父, 属性=attr, 起=起)
        self.收(sid, 止=起)          # 模型调用是「收到时才知道它发生过」,起止同一刻
        return sid

    def 一次工具调用(self, *, 父, 工具, 参数, 调用号=None, 起=None):
        a, 截 = 装值(参数)
        return self.开("execute_tool", f"execute_tool {工具}", 父=父, sid=调用号, 起=起,
                       属性={"gen_ai.tool.name": 工具, "gen_ai.tool.call.id": 调用号,
                            "gen_ai.tool.type": "function",
                            "gen_ai.tool.call.arguments": a,
                            "lanxiu.arguments.truncated": True if 截 else None})

    def 工具回来了(self, 调用号, 返回, *, 出错=False, 止=None):
        r, 截 = 装值(返回)
        self.收(调用号, 止=止,
                属性={"gen_ai.tool.call.result": r,
                     "lanxiu.result.truncated": True if 截 else None},
                出错="tool_error" if 出错 else None)

    # ── 落盘 ──────────────────────────────────────────────────────
    def 落盘(self, path=None):
        p = path or LOG
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if os.path.getsize(p) > 轮转字节: os.replace(p, p + ".1")
        except OSError:
            pass
        now = time.time()
        for s in self.spans:
            if s["end"] is None:                # 没收的 span:别丢,标出来
                s["end"] = now
                if s["status"] == "unset": s["status"] = "未收尾"
            s["duration_ms"] = round(max(0.0, s["end"] - s["start"]) * 1000)
            s["ts"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["start"]))
            for k, v in self.元.items():
                if v is not None: s.setdefault(k, v)
        with open(p, "a", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        return len(self.spans)


# ── 读回来 ─────────────────────────────────────────────────────────
def 读(path=None, 限=None):
    """{trace_id: [span, ...]},按时间排。限=只要最近几棵。"""
    p = path or LOG
    if not os.path.exists(p): return {}
    出 = {}
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try: s = json.loads(line)
        except Exception: continue
        出.setdefault(s.get("trace_id", "?"), []).append(s)
    for v in 出.values(): v.sort(key=lambda s: s.get("start", 0))
    棵 = sorted(出.items(), key=lambda kv: kv[1][0].get("start", 0))
    if 限: 棵 = 棵[-限:]
    return dict(棵)


def 排成树(spans):
    """[(缩进层数, span), ...] —— 按父子关系深度优先排开。

    **孤儿要出现在输出里**(父不在这棵树里的),不能悄悄丢:
    丢了的表现是「这一步没发生过」,而真相是「记的时候父子对不上」,
    这两件事在页面上长得一模一样。
    """
    有 = {s["span_id"] for s in spans}
    子 = {}
    for s in spans:
        p = s.get("parent_span_id")
        子.setdefault(p if p in 有 else None, []).append(s)
    出 = []

    def 走(p, 深):
        for s in sorted(子.get(p, []), key=lambda x: x.get("start", 0)):
            出.append((深, s))
            走(s["span_id"], 深 + 1)
    走(None, 0)
    return 出


def 一棵的账(spans):
    """这一棵花了多少、用了多少 token、几次工具。

    ⚠️ **不许把所有 span 的用量加起来。** 根上挂的是整轮的汇总,每次模型调用上
    挂的是这一步的 —— 全加一遍等于每个数都算了两次
    (2026-09-24 页面上当场露馅:缓存命中 10.8 万显示成 43 万)。
    **有根就以根为准**(它是 SDK 给的权威数),根上没有才退回去按步加。
    """
    根 = next((s for s in spans if not s.get("parent_span_id")), None)
    步 = [s for s in spans if s is not 根]

    def 取(键, 兜底=0):
        v = (根 or {}).get("attr", {}).get(键)
        return v if v is not None else sum(s["attr"].get(键) or 0 for s in 步) or 兜底

    钱 = 取("lanxiu.cost_usd")
    if not 钱:      # 根上没有真实计价时,退回各步的输入侧(说得清是哪一半)
        钱 = sum(s["attr"].get("lanxiu.cost_usd.input_side") or 0 for s in 步)
    进, 出 = 取("gen_ai.usage.input_tokens"), 取("gen_ai.usage.output_tokens")
    命中 = 取("gen_ai.usage.cache_read_input_tokens")
    工具 = [s for s in spans if s["attr"].get("gen_ai.operation.name") == "execute_tool"]
    模型 = [s for s in spans if s["attr"].get("gen_ai.operation.name") == "chat"]
    return dict(spans=len(spans), 模型调用=len(模型), 工具调用=len(工具),
                成本=round(钱, 6), 输入=进, 输出=出, 缓存命中=命中,
                耗时秒=round(max((s.get("duration_ms") or 0) for s in spans) / 1000, 1) if spans else 0,
                出错=[s["name"] for s in spans if s.get("status") == "error"])


# ── 自测 ───────────────────────────────────────────────────────────
def _自测():
    import tempfile
    过, 挂 = [], []

    def ck(名, 真, 补=""):
        (过 if 真 else 挂).append(名)
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")

    t = 一棵树(角色="门店顾问", 会话号="s1", 模型="deepseek-chat", 供应商="deepseek")
    根 = t.开("invoke_agent", "invoke_agent 门店顾问",
              属性={"gen_ai.agent.name": "门店顾问", "gen_ai.conversation.id": "s1"})
    c1 = t.一次模型调用(父=根, 模型="deepseek-chat",
                        usage={"input_tokens": 12, "output_tokens": 3,
                               "cache_read_input_tokens": 900}, 花费=0.001)
    g1 = t.一次工具调用(父=c1, 工具="get_order", 调用号="tu_1",
                        参数={"order_id": "DD2601", "密码": "不该出现"})
    t.工具回来了("tu_1", {"状态": "已发货", "salt": "也不该出现"})
    子 = t.开("execute_tool", "execute_tool Task", 父=c1, sid="tu_2")
    t.开("chat", "chat 子助手", 父="tu_2")          # 子助手里的调用挂在工具下面
    t.收(子)
    t.收(根)

    ck("凭据按键名抹掉(参数)", 抹了 in t.找("tu_1")["attr"]["gen_ai.tool.call.arguments"])
    ck("凭据按键名抹掉(返回值)", 抹了 in t.找("tu_1")["attr"]["gen_ai.tool.call.result"])
    ck("没被抹的照常留着", "DD2601" in t.找("tu_1")["attr"]["gen_ai.tool.call.arguments"])
    # 用量计数的字段名里带 tokens,**不许被当成凭据** —— 第一版就栽在这儿
    ck("input_tokens / cache_read_input_tokens 不算凭据",
       not any(凭据键.search(k) for k in
               ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
                "gen_ai.usage.cache_read_input_tokens",
                "gen_ai.usage.cache_creation_input_tokens")))
    ck("真凭据还是认得出来",
       all(凭据键.search(k) for k in ("access_token", "密码", "api_key", "salt", "口令")))

    global 上限
    旧 = 上限; 上限 = 20
    s, 截 = 装值("一" * 100)
    ck("超长截断并标出来", 截 and len(s) < 100 and "未记" in s)
    上限 = 旧

    p = os.path.join(tempfile.mkdtemp(), "spans.jsonl")
    n = t.落盘(p)
    ck("落盘行数 = span 数", n == len(t.spans), n)
    回 = 读(p)
    ck("读回来还是一棵", len(回) == 1 and len(list(回.values())[0]) == n)
    rows = list(回.values())[0]
    ck("span_id 不重复", len({s["span_id"] for s in rows}) == len(rows))
    ck("父都在这棵树里", all((s.get("parent_span_id") or s["span_id"]) in
                            {x["span_id"] for x in rows} for s in rows))
    ck("耗时不为负", all((s.get("duration_ms") or 0) >= 0 for s in rows))
    树 = 排成树(rows)
    ck("排成树不丢 span", len(树) == len(rows), f"{len(树)}/{len(rows)}")
    ck("子助手的调用嵌在工具下面(深度到 3)", max(d for d, _ in 树) >= 3,
       [(d, s["name"]) for d, s in 树])

    # 孤儿:父不在这棵树里的,必须照样出现(而不是被悄悄吃掉)
    孤 = dict(rows[0]); 孤 = json.loads(json.dumps(孤))
    孤.update(span_id="孤儿", parent_span_id="根本不存在", name="孤儿 span")
    ck("父找不到的 span 不会被吃掉", len(排成树(rows + [孤])) == len(rows) + 1)

    账 = 一棵的账(rows)
    # 根上有整轮汇总、步上有分步值时,**不许两边相加**(算两遍)
    根 = next(x for x in rows if not x.get("parent_span_id"))
    根["attr"]["gen_ai.usage.cache_read_input_tokens"] = 900
    ck("有根汇总时以根为准,不和分步相加", 一棵的账(rows)["缓存命中"] == 900,
       一棵的账(rows)["缓存命中"])
    根["attr"].pop("gen_ai.usage.cache_read_input_tokens")
    # 夹具里是 2 次模型调用(主 + 子助手那次)、2 次工具(get_order + Task)——
    # 第一版这里写的是 1,**是断言写错了不是代码错了**:子助手那一层就是要被算进来的
    ck("账算得出:2 次模型调用、2 次工具、缓存命中 900",
       账["模型调用"] == 2 and 账["工具调用"] == 2 and 账["缓存命中"] == 900, 账)

    # 没收尾的 span 要被标出来,不能当成正常结束
    t2 = 一棵树(角色="x"); r2 = t2.开("invoke_agent", "没收尾的")
    p2 = os.path.join(tempfile.mkdtemp(), "s.jsonl"); t2.落盘(p2)
    ck("没收尾的 span 标成「未收尾」",
       list(读(p2).values())[0][0]["status"] == "未收尾")

    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_自测())
    棵 = 读(限=int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1)
    if not 棵:
        print("还没有记录。跑一次智能体就会有(树状记录仪写 .feynman/spans.jsonl)。")
        raise SystemExit
    for tid, spans in 棵.items():
        账 = 一棵的账(spans)
        print(f"\ntrace {tid[:12]} · {spans[0].get('ts')} · {spans[0].get('角色')} · "
              f"{账['耗时秒']}s · ${账['成本']} · 模型 {账['模型调用']} 次 / 工具 {账['工具调用']} 次")
        print("-" * 96)
        for 深, s in 排成树(spans):
            a = s["attr"]
            尾 = ""
            if a.get("gen_ai.operation.name") == "chat":
                尾 = (f"  入{a.get('gen_ai.usage.input_tokens')}"
                      f" 命中{a.get('gen_ai.usage.cache_read_input_tokens')}"
                      f" 出{a.get('gen_ai.usage.output_tokens')}"
                      f" ${a.get('lanxiu.cost_usd')}")
            elif a.get("gen_ai.operation.name") == "execute_tool":
                尾 = "  " + (a.get("gen_ai.tool.call.arguments") or "")[:60]
            print(f"  {'│  ' * 深}{'✗' if s['status']=='error' else '·'} "
                  f"{s['name']:<38s} {s.get('duration_ms',0):>6d}ms{尾}")
