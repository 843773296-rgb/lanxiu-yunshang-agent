# -*- coding: utf-8 -*-
"""结论 ↔ 证据逐句核对(证据中心需求文档 3.6;算法见附录 A-5,用户 10-25 选「规则逐句比对」)。

**不调模型**。把这一轮的回答拆成句,从每句里抽出能核对的值 —— 单号、日期、带单位的数、金额 ——
去**这一轮工具真实返回的数据**里找(先用原文,原文没有才用展示副本,并标出来):

  已核对   句里的单号找到了,同一条记录里日期 / 数值也对得上;没有单号的句子,值在本轮返回里找到了(标「没绑到具体记录」)
  存在冲突 单号找到了,但句里的日期 / 数值不在那条记录里;或者说「已派 / 已创建 / 已保存」而这一轮没有写入成功的回执
  缺少依据 这些值在这一轮所有返回里都找不到(单号没取过、数是凭空来的)
  未判定   抽不出可核对的值(推断、建议、话术)—— **不硬凑依据**

「同一条记录」= 单号所在的那个对象往上走,走到「列表里的一项」或整个返回为止(名单里每个客户一项,
详情工具整个返回就是那一个客户)。**列表项小标题里的单号管到它下面的小点**(「**1. 张青梧(C10026)**」下面的
「闲置 5 天」核的是 C10026 那条)—— 这是 10-25 拿 12 条真实回答试拆看出来的:单号常常只写在小标题里。

「超期 N 天 / N 天后 / N 天前」返回里没有现成的数时,用句里的日期按**业务今天**重算(调用方给;不给就不重算)。

首版局限(写进 PRD A-5):推断和建议只标未判定,不判断说得对不对;「上周三」这类相对说法对不上「10-22」,会落成缺少依据;
没有单号的小数字(「6 条」)在大返回里碰巧出现的概率不低,所以只认「数值字段相等」或「同一个单位跟在后面」,并标弱。
纯函数,不碰库不碰文件;`claims_check.py` 逐条真调它。依据里只给工具名、调用号和字段路径,不带原文片段 ——
这口子跟执行记录同权限,原文正文要另走 /spans/raw 的专项授权。
"""
import datetime as _dt
import json
import re

状态们 = ("已核对", "存在冲突", "缺少依据", "未判定")

# ── 抽值 ────────────────────────────────────────────────────────────────
# 单号:字母前缀 + 至少两位数字(KF02 / C10026 / SH001 / lxys_101100741-04);纯数字只认 8 位以上(工号 60000012、订单号)
_单号 = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,6}_?\d{2,}(?:-\d{1,3})?)(?![A-Za-z0-9_])|(?<![\d.])(\d{8,})(?![\d.])")
_日期 = re.compile(r"(?<!\d)(?:(20\d{2})\s*[-/年]\s*)?(\d{1,2})\s*(?:-|/|月)\s*(\d{1,2})(?:\s*日)?(?!\d)")
_单位 = "元|件|个月|个|年|天|单|条|笔|项|工日|人|位|次|小时|分钟|周|%|倍|张|款|家|SKU"
_带单位 = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(万)?\s*(" + _单位 + r")")
_币 = re.compile(r"[¥￥$]\s*(\d[\d,]*(?:\.\d+)?)")
_天差 = re.compile(r"(?:(超期|逾期|晚了|过了|拖了)\s*(\d+)\s*天)|(?:(\d+)\s*天(前|后|之后|以前))")
# 说「已经做了」的句子:第一人称完成体才算(「已经派出去的旧单」「我可以帮你派」都不算 —— 10-25 真实回答里这两种都有)
_动词 = "派|派发|创建|新建|建好|建了|关闭|关掉|关了|保存|存好|存了|提交|分派|改派|开单|开好|登记|录入|下单"
_动作 = re.compile(r"(?:我(?:已经?|刚刚?)|(?:已经?|刚刚?)(?:为你|帮你|给你|替你))[^,，。;；]{0,12}?(?:" + _动词 + r")"
                 r"|^(?:已经?|刚刚?)(?:" + _动词 + r")(?:了|好|完)")
_句界 = re.compile(r"(?<=[。！？；!?;])")
# 举例:「比如 C10001」「格式如 2026-10-30 18:00」—— 值是示范写法,不是在说事实(10-25 用户实测:被判成缺少依据 / 已核对)。
# 从标记往后到这个小句结束都算举例;不认单字「如」(「如果」「如下」)
_举例 = re.compile(r"(?:比如|例如|譬如|诸如|格式如|格式为|格式是|形如|举个例子?|举例|e\.g\.)\s*[:：]?")
_小句尾 = re.compile(r"[，,。；;）)\n]")
_标题行 = re.compile(r"^\s*(?:#{1,6}\s|\*\*\s*\d+[.、]|\d+[.、]\s*\*\*|\d+[.、]\s)")
_小点 = re.compile(r"^\s*(?:[-*•]\s|\d+[.)]\s)")
_表分隔 = re.compile(r"^\s*\|?\s*:?-{2,}")


def _数(s):
    return float(str(s).replace(",", ""))


def 抽值(句):
    """一句 → [{类: 单号/日期/数, 原样, 值, (单位, 位数)}]。单号先抽,抽掉的那段不再拿去当日期和数。"""
    出, 占 = [], []
    for m in _单号.finditer(句):
        出.append({"类": "单号", "原样": m.group(0), "值": m.group(0)}); 占.append(m.span())
    def 空(sp): return not any(a < sp[1] and sp[0] < b for a, b in 占)
    for m in _日期.finditer(句):
        if not 空(m.span()):
            continue
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        # 「5-7 天」是区间不是日期:后面紧跟单位的不算
        if re.match(r"\s*(?:" + _单位 + ")", 句[m.end():]):
            continue
        出.append({"类": "日期", "原样": m.group(0), "值": (int(y) if y else None, mo, d)}); 占.append(m.span())
    for m in _带单位.finditer(句):
        if not 空(m.span()):
            continue
        v = _数(m.group(1)) * (10000 if m.group(2) else 1)
        位 = len(m.group(1).split(".")[1]) if "." in m.group(1) and not m.group(2) else 0
        出.append({"类": "数", "原样": m.group(0), "值": v, "单位": m.group(3), "位数": 位}); 占.append(m.span())
    for m in _币.finditer(句):
        if 空(m.span()):
            位 = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
            出.append({"类": "数", "原样": m.group(0), "值": _数(m.group(1)), "单位": "元", "位数": 位}); 占.append(m.span())
    return 出


def _去标记(s):
    s = re.sub(r"[*`>#]+", "", s)
    s = re.sub(r"^\s*(?:[-•]\s*|\d+[.、)]\s*)", "", s)
    return s.strip()


def 拆句(答案):
    """回答 → [{句, 上下文单号}]。按行、再按句末标点拆;表格一行算一句;小标题里的单号传给下面的小点。"""
    出, 上下文 = [], []
    for 行 in str(答案 or "").split("\n"):
        if not 行.strip() or _表分隔.match(行):
            continue
        行单号 = [m.group(0) for m in _单号.finditer(行)]
        if _标题行.match(行):
            上下文 = 行单号
            承 = []
        elif _小点.match(行) or 行.lstrip().startswith("|"):
            承 = list(上下文)
        else:
            上下文, 承 = [], []
        if 行.lstrip().startswith("|"):
            片们 = [" ".join(c.strip() for c in 行.strip().strip("|").split("|"))]
        else:
            片们 = _句界.split(行)
        for 片 in 片们:
            t = _去标记(片)
            if len(re.sub(r"[\W_]", "", t)) < 2:
                continue
            出.append({"句": t, "上下文单号": [x for x in 承 if x not in t]})
    return 出


# ── 证据 ────────────────────────────────────────────────────────────────
def _解(s):
    try:
        x = json.loads(s) if isinstance(s, str) else s
    except Exception:
        return s
    # MCP 有时包一层 [{"type":"text","text":"{...}"}]
    if isinstance(x, list) and x and all(isinstance(i, dict) and i.get("type") == "text" for i in x):
        return _解("".join(str(i.get("text") or "") for i in x))
    return x


def _叶子(x, 路=(), 祖=()):
    """→ [(路径, 值, 记录根路径)]。记录根 = 往上走到「列表里的一项」或整个返回。"""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _叶子(v, 路 + (k,), 祖)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _叶子(v, 路 + (i,), 祖 + (路 + (i,),))
    else:
        yield 路, x, (祖[-1] if 祖 else ())


def 证据(rows, 原文条=None):
    """一轮的 spans + 原文 → [{工具, 调用号, 是原文, 叶子:[(路径, 值, 记录根)]}]。找工具 / 加载技能这两种内置步骤不算。"""
    原 = {(x.get("span"), x.get("哪段")): x.get("内容") for x in (原文条 or []) if x.get("校验") == "一致"}
    出 = []
    for s in rows or []:
        a = s.get("attr") or {}
        if a.get("gen_ai.operation.name") != "execute_tool":
            continue
        名 = str(a.get("gen_ai.tool.name") or "").rsplit("__", 1)[-1]
        if 名 in ("ToolSearch", "Skill"):
            continue
        号 = a.get("gen_ai.tool.call.id")
        r = 原.get((s.get("span_id"), "返回"))
        if r is None and 号:
            r = 原.get((号, "返回"))
        是原文 = r is not None
        if r is None:
            r = a.get("gen_ai.tool.call.result")
        if r is None:
            continue
        出.append({"工具": 名, "调用号": 号, "span": s.get("span_id"), "是原文": 是原文,
                   "状态": s.get("status"), "叶子": list(_叶子(_解(r)))})
    return 出


def _路(p):
    return ".".join(f"[{x}]" if isinstance(x, int) else str(x) for x in p) or "(整个返回)"


# 单位按族比:「17 个测量项」顶得上「17 项」,顶不上「17 天」(10-25 试拆:量词写法在回答和返回里常不一样)
_族 = {**{u: "量" for u in "个 件 单 条 笔 项 人 位 次 张 款 家 SKU".split()},
       **{u: "时" for u in "天 小时 分钟 周 工日".split()}, "个月": "月"}


def _同族(a, b):
    return a == b or (a in _族 and _族.get(a) == _族.get(b))


def _串里的数(s):
    # 先抹掉日期和钟点:「2026-09-20」里的 09 不是「9 天」
    s = re.sub(r"\d{1,2}:\d{2}", " ", _日期.sub(" ", str(s)))
    return [(_数(m.group(1)), m.group(2) or "") for m in
            re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(" + _单位 + r")?", s)]


def _数对上(要, 叶, 严):
    """答案里的数 ↔ 一个叶子。按答案写的位数四舍五入比;% 也认小数写法。严 = 没绑到记录时只认数值字段或同单位。"""
    def 等(x):
        for 候 in ((x, x * 100) if 要.get("单位") == "%" else (x,)):
            if abs(round(候, 要["位数"]) - 要["值"]) < 1e-9 or abs(候 - 要["值"]) < 1e-9:
                return True
        return False
    if isinstance(叶, bool):
        return False
    if isinstance(叶, (int, float)):
        return 等(float(叶))
    # 串里的数:单位要么一样、要么没写单位(「5 个测量项」不能顶「闲置 5 天」);没绑到记录时只认同单位
    for v, u in _串里的数(叶):
        if 等(v) and (_同族(u, 要.get("单位")) or (not 严 and not u)):
            return True
    return False


def _日对上(要, 叶):
    if not isinstance(叶, str):
        return False
    y, mo, d = 要["值"]
    for m in _日期.finditer(叶):
        yy, mm, dd = m.group(1), int(m.group(2)), int(m.group(3))
        if (mm, dd) == (mo, d) and (y is None or yy is None or int(yy) == y):
            return True
    return False


def _单号在(号, 叶):
    return isinstance(叶, (str, int)) and re.search(r"(?<![A-Za-z0-9_])" + re.escape(str(号)) + r"(?![A-Za-z0-9_])", str(叶))


def _找(要, 证们, 范围=None, 严=False):
    """在证据里找一个值 → 第一处依据 {工具, 调用号, 路径, 是原文} 或 None。范围 = {(第几个证据, 记录根)}。"""
    for i, e in enumerate(证们):
        for 路, 叶, 根 in e["叶子"]:
            if 范围 is not None and not any(i == j and 路[:len(r)] == r for j, r in 范围):
                continue
            ok = (_单号在(要["值"], 叶) if 要["类"] == "单号" else
                  _日对上(要, 叶) if 要["类"] == "日期" else _数对上(要, 叶, 严))
            if ok:
                return {"工具": e["工具"], "调用号": e["调用号"], "路径": _路(路), "是原文": e["是原文"]}
    return None


def _记录(号, 证们):
    return {(i, 根) for i, e in enumerate(证们) for 路, 叶, 根 in e["叶子"] if _单号在(号, 叶)}


def _是记录键(号, 证们):
    """单号在每次返回里最多落在一条记录上(落在好几条上的是门店、工号这类分组维度)。"""
    from collections import Counter
    n = Counter(i for i, 根 in _记录(号, 证们))
    return bool(n) and max(n.values()) == 1


def _写成功(e, 写工具):
    if e["工具"] not in 写工具 or e.get("状态") == "error":
        return False
    for 路, 叶, _ in e["叶子"]:
        if 路[:1] == ("error",) or 路[:1] == ("错误",):
            return False
    return True


def _是天差(句, 要):
    return any(str(int(要["值"])) in m.group(0) for m in _天差.finditer(句)) and any(v["类"] == "日期" for v in 抽值(句))


def _重算天差(句, 要, 业务今天):
    """「超期 3 天 / 4 天后」+ 句里的日期 → (对上了吗, 理由) 或 None(没法重算)。"""
    if not 业务今天:
        return None
    m = next((m for m in _天差.finditer(句) if (m.group(0).find(str(int(要["值"]))) >= 0)), None)
    if not m:
        return None
    日们 = [v["值"] for v in 抽值(句) if v["类"] == "日期"]
    if not 日们:
        return None
    y, mo, d = 日们[0]
    今 = 业务今天 if isinstance(业务今天, _dt.date) else _dt.date.fromisoformat(str(业务今天)[:10])
    try:
        那天 = _dt.date(y or 今.year, mo, d)
    except ValueError:
        return None
    差 = (今 - 那天).days if (m.group(1) or m.group(4) in ("前", "以前")) else (那天 - 今).days
    return 差 == int(要["值"]), f"按业务今天 {今.isoformat()} 重算是 {差} 天"


def _举例段(句):
    段 = []
    for m in _举例.finditer(句):
        尾 = _小句尾.search(句, m.end())
        段.append((m.end(), 尾.start() if 尾 else len(句)))
    return 段


def 核一句(句, 上下文单号, 证们, 写工具=(), 业务今天=None):
    值们 = 抽值(句)
    段 = _举例段(句)
    if 段:
        # 按出现顺序定位,同一个原样出现两次时各算各的位置
        剩, 起 = [], {}
        for v in 值们:
            i = 句.find(v["原样"], 起.get(v["原样"], 0))
            起[v["原样"]] = i + 1
            if not any(a <= i < b for a, b in 段):
                剩.append(v)
        if 值们 and not 剩 and not _动作.search(句):
            return {"状态": "未判定", "值": [], "依据": [], "理由": "句里的值是举例(比如 / 格式如),不是在说事实"}
        值们 = 剩
    if _动作.search(句):
        回执 = [e for e in 证们 if _写成功(e, 写工具)]
        if 回执:
            return {"状态": "已核对", "值": [], "理由": f"这一轮有写入成功的回执({回执[0]['工具']})",
                    "依据": [{"工具": 回执[0]["工具"], "调用号": 回执[0]["调用号"], "路径": "(整个返回)", "是原文": 回执[0]["是原文"]}]}
        return {"状态": "存在冲突", "值": [], "依据": [],
                "理由": "说已经做了,这一轮没有写入成功的回执" + ("(一个写工具都没调)" if not any(e["工具"] in 写工具 for e in 证们) else "(写工具报错了)")}
    if not 值们:
        return {"状态": "未判定", "值": [], "依据": [], "理由": "抽不出可核对的值(推断 / 建议 / 话术)"}
    结果, 依据 = [], []
    句单号 = [v["值"] for v in 值们 if v["类"] == "单号"]
    # 只在「这句说的是一条记录」时才绑:恰好一个单号,而且它在每次返回里最多落在一条记录上。
    # 10-25 试拆:「6 条(本店 SH001)」—— SH001 落在 6 条差评上,它是分组维度不是记录键,6 是总数;
    # 「67 位高风险客户(例如 C36892、C36090)」—— 两个单号是举例,67 是总数。这两种绑上去都会误判冲突
    键们 = [号 for 号 in dict.fromkeys(句单号 + list(上下文单号 or [])) if _是记录键(号, 证们)]
    范围 = _记录(键们[0], 证们) if len(键们) == 1 else set()
    绑了 = 键们[0] if 范围 else ""
    for v in 值们:
        if v["类"] == "单号":
            处 = _找(v, 证们)
            结果.append({"原样": v["原样"], "判": "对上" if 处 else "没找到",
                         "理由": None if 处 else "这个单号这一轮没取过"})
        elif 范围:
            处 = _找(v, 证们, 范围)
            if not 处:
                别处 = _找(v, 证们, 严=True)
                结果.append({"原样": v["原样"], "判": "对不上",
                             "理由": f"{绑了} 那条记录里没有这个值" + ("(本轮别的返回里有)" if 别处 else "")})
        else:
            处 = _找(v, 证们, 严=True)
            if 处:
                处 = {**处, "弱": "没绑到具体记录"}
            else:
                结果.append({"原样": v["原样"], "判": "没找到", "理由": "这一轮的返回里都找不到"})
        if v["类"] != "单号" and not 处 and v["类"] == "数" and v.get("单位") == "天":
            重 = _重算天差(句, v, 业务今天)
            if 重:
                结果[-1] = {"原样": v["原样"], "判": "对上" if 重[0] else "对不上", "理由": 重[1]}
                if 重[0]:
                    处 = {"工具": None, "调用号": None, "路径": "按业务日期重算", "是原文": None}
            elif not 业务今天 and _是天差(句, v):
                # 没有那一轮当时的业务日期:算不了,不能因此判它冲突 —— 落缺少依据,理由写明
                结果[-1] = {"原样": v["原样"], "判": "没找到", "理由": "返回里没有现成的天数,又没有当时的业务日期,没法重算"}
        if 处:
            依据.append({**处, "值": v["原样"]})      # 每条依据标明对的是哪个值 —— 面板逐个列(10-25:原来只显示第一条)
            if v["类"] != "单号":
                结果.append({"原样": v["原样"], "判": "对上", "理由": None})
    判们 = {x["判"] for x in 结果}
    状 = "存在冲突" if "对不上" in 判们 else "缺少依据" if "没找到" in 判们 else "已核对"
    理由 = "；".join(f"{x['原样']}:{x['理由']}" for x in 结果 if x["判"] != "对上" and x["理由"]) or None
    if 状 == "已核对" and not 范围:
        理由 = "值在本轮返回里找到了,没绑到具体记录"
    return {"状态": 状, "值": 结果, "依据": 依据, "理由": 理由}


def 核对(答案, rows, 原文条=None, 写工具=(), 业务今天=None):
    """一轮 → {句们:[{句, 状态, 值, 依据, 理由}], 计数, 说明}。"""
    证们 = 证据(rows, 原文条)
    写工具 = {str(t).rsplit("__", 1)[-1] for t in 写工具 or ()}
    句们 = [{"句": x["句"], **核一句(x["句"], x["上下文单号"], 证们, 写工具, 业务今天)} for x in 拆句(答案)]
    计数 = {k: sum(1 for x in 句们 if x["状态"] == k) for k in 状态们}
    展示 = sum(1 for e in 证们 if not e["是原文"])
    说明 = ("规则逐句比对,不调模型:单号 / 日期 / 带单位的数 / 金额,去这一轮工具的真实返回里找;推断和建议标未判定,不判断说得对不对。"
            + ("" if 证们 else "这一轮没有可核对的工具返回 —— 带值的句子全落在缺少依据。")
            + (f"有 {展示} 次调用没有原文,用的是展示副本(可能截过、手机号打过码)。" if 展示 else "")
            + ("" if 业务今天 else "没给业务日期,「超期 N 天」不重算,只认返回里的现成数。")
            + ("回答在记录里被截断了,后半段没核。" if "〔还有" in str(答案 or "") else ""))
    return {"句们": 句们, "计数": 计数, "说明": 说明}


# ── 下面这个**读库**,不是纯函数:聊天站 /spans 和推送管理后台(tools/spans_push.py)共用,不各写一份 ──
def 当时的业务今天(开始, 库=None):
    """「超期 N 天」重算要用**那一轮当时的**业务日期。世界每天平移一次(world_meta.shifted_at):
    这一轮在最近一次平移之后跑的,当时的业务今天就是现在的 world_today;更早的给 None(不重算,说明里写明)。"""
    import os
    import sqlite3
    库 = 库 or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "lanxiu.db")
    try:
        c = sqlite3.connect(f"file:{库}?mode=ro", uri=True)
        kv = dict(c.execute("select k, v from world_meta where k in ('world_today', 'shifted_at')").fetchall())
        c.close()
        if 开始 and kv.get("shifted_at") and float(开始) >= _dt.datetime.fromisoformat(kv["shifted_at"]).timestamp():
            return kv.get("world_today")
    except Exception:
        pass
    return None
