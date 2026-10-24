#!/usr/bin/env python3
"""提示词单一源头检查。

这个检查是补票买的。发现时的实况:同一个「后台人工任务助手」角色有 **3 份**
提示词(agent/v1.py 4 条铁律、agentsite/sdk.py 6 条、agent/chat.py 是另一个角色的 6 条),
互相之间漂了很久:

  · **评测跑的是 chat.py 那份,给出的分数评的不是产品**;
  · 三代对比里 V1 少带了「客户合并判定标准」——
    而那条是有实测的:不给 0/2,给了 2/2。V1 是少带一条已知能加分的规矩上的场。

一份手抄件不会自己告诉你它旧了。所以这里查四件事。
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "backend"))
import prompts, api

bad = []
# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('让 TL29 依赖一个不存在的工具',
     '铁律依赖的工具必须真实存在'),
    ('让 TL58(不让价)落到一个永不执行的分支上 —— 源码里还在,没有角色装它',
     '定义了的规矩都被某个角色装上了'),
    ('规矩改成跟着运行时取回的工具装(按需加载之后 P6 就成了摆设)',
     '规矩按名单启动时装配,不跟着运行时取回的工具走'),
]

def rule(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    for r in rows[:6]: print(f"        · {r}")
    if rows: bad.append((no, why, len(rows)))

# ── P1:唯一源头 ────────────────────────────────────────────────────
# 角色开场白拼出来,**不写成一个完整字面量** —— 否则这个文件自己会被扫中。
# (密钥扫描在同一个坑里栽过四次:规则字符串写进被扫文件,自己匹配自己。)
OPEN = "你是澜绣" + "云裳"
import rating as RT方式          # P10 要拿处理方式枚举(名单的唯一源头)
SRC_OK = {"prompts.py", "prompts_check.py"}
hits = []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in (".git", ".venv", "__pycache__", "node_modules")]
    for fn in fns:
        if not fn.endswith(".py") or fn in SRC_OK: continue
        fp = os.path.join(dp, fn)
        src = open(fp, encoding="utf-8").read()
        for m in re.finditer(r'^([A-Za-z_]\w*)\s*=\s*"""(.*?)"""', src, re.S | re.M):
            if OPEN in m.group(2):
                n = len([l for l in m.group(2).splitlines() if re.match(r"^\d+\. ", l)])
                hits.append(f"{os.path.relpath(fp, ROOT)}:{m.group(1)}(铁律 {n} 条)")
rule("P1", "提示词只能有一处定义", hits,
     "手抄件不会自己告诉你它旧了 —— 要么 import prompts,要么它迟早和产品对不上")

# ── P2:needs / avoid 里的工具名必须真实存在 ────────────────────────
REAL = set(api.TOOLS) | {"图片", "submit_finding"}
ghost = [f"{r.id} 依赖 {n}(不存在这个工具)"
         for _, r in prompts.all_rules(unique=True) for n in r.needs + r.avoid if n not in REAL]
rule("P2", "铁律依赖的工具必须真实存在", ghost,
     "工具名打错了不会报错,只会让那条铁律**永远装不上** —— 静默失效")

# ── P3:每条铁律至少被一个真实调用方装上 ────────────────────────────
# 调用方的工具清单从源码里取(不 import sdk:它要 claude_agent_sdk,没装就跑不了)。
SDK = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
def wl(name):
    m = re.search(rf"^{name} = \[(.*?)\]", SDK, re.S | re.M)
    return {t.rsplit("__", 1)[-1] for t in re.findall(r'"([^"]+)"', m.group(1))} if m else set()
KB, SHOP, TASK = wl("KB_TOOLS"), wl("SHOP_TOOLS"), wl("TASK_TOOLS")
KBONLY, WORK = wl("KB_ONLY_TOOLS"), wl("WORKSHOP_TOOLS")
TASKONLY = wl("TASK_ONLY_TOOLS")
# 发起被接管的工作流(10-24):sdk 里**每个角色**都拼上这一组。这里漏拼的话 TL76 「没有调用方装得上」——
# 而它真装上了,是这张手抄的组合表跟丢了。真名单由 agentsite/takeover_check.py 从 sdk._ROLE_TOOLS 现取核对
TAKEOVER = wl("TAKEOVER_TOOLS")
KBSET = {t["name"] for t in api.KB_SCHEMAS}
CALLERS = {
    "工作站·全能助手(sdk)":   ("all",  KB | KBONLY | WORK | TASK | TASKONLY | SHOP | TAKEOVER | {"图片"}),
    "工作站·工艺顾问(sdk)":   ("kb",   KB | KBONLY | SHOP | TAKEOVER | {"图片"}),
    "工作站·工坊排产(sdk)":   ("workshop", WORK | TAKEOVER),
    # ⚠️ **新角色要加到这儿,否则 P3/P6 根本不看它。**
    # 财务角色刚加上时忘了这一行 —— 于是它挂了 5 个工具、拿了 4 条规矩,
    # 而 P6 一个字都没验过它。**一条检查漏掉某个调用方,
    # 和这个调用方不存在,在检查输出上长得一模一样。**
    "工作站·财务对账(sdk)":   ("finance", wl("FINANCE_TOOLS") | TAKEOVER),
    # 上面那条注释说的事又发生了一次:加版师角色时忘了这一行,
    # P3 当场红「TL25 没有任何调用方装得上」—— **而它拦对了**:
    # 一条装不上的铁律和一条不存在的铁律,在源码里长得一模一样。
    "工作站·版师核料(sdk)":   ("pattern", wl("PATTERN_TOOLS") | TAKEOVER),
    # 第三次了 —— 财务漏过、版师漏过,所以建售后角色时**先加这一行再写别的**。
    "工作站·售后(sdk)":       ("aftersale", wl("AFTERSALE_TOOLS") | TAKEOVER),
    "工作站·任务助手(sdk)":   ("task", TASK | TASKONLY | SHOP | TAKEOVER),
    "后台聊天(chat.py)":      ("kb",   KBSET),
    "一代任务循环(v1.py)":    ("task", {t["name"] for t in api.SCHEMAS} | {"submit_finding"}),
}
used = set()
print()
for nm, (role, have) in CALLERS.items():
    _, ids = prompts.assemble(role, have)
    used |= set(ids)
    print(f"     {nm:26s} {len(ids):2d} 条  {' '.join(ids)}")
print()
orphan = [f"{r.id}(需要 {r.needs or '—'},没有任何调用方满足)"
          for _, r in prompts.all_rules(unique=True) if r.id not in used]
rule("P3", "每条铁律至少要有一个调用方装得上", orphan,
     "装不上的铁律等于不存在,而它看起来一直好好地躺在源码里 —— "
     "和「没有用例的规则」是同一个病")

# ── P5:工具级规矩必须**恰好**依赖一个工具 ─────────────────────────
# scope="工具" 的那几条是贴在工具旁边渲染的,渲染时取 needs[0] 当标题。
# 依赖零个工具就不知道贴谁旁边,依赖两个就会贴错一个 ——
# 原来的第 12 条正是这个毛病:把「工期 kb_lead」和「产能 get_capacity」写在一条里,
# 于是有 kb_lead 没 get_capacity 的调用方整条都拿不到。拆开之后才对得上。
_p5 = [f"{r.id} 依赖 {len(r.needs)} 个工具({r.needs or '零个'}),贴不到工具旁边"
       for _, r in prompts.all_rules(unique=True) if r.scope == "工具" and len(r.needs) != 1]
rule("P5", "工具级规矩必须恰好依赖一个工具", _p5,
     "工具用法要贴着工具写 —— 依赖零个不知道贴谁,依赖两个必然贴错一个")

# ── P6:挂了某个工具,就必须拿到那个工具的规矩 ───────────────────────
# P3 查的是「规矩有没有调用方」,方向是 规矩 → 调用方。
# 这一条查反方向:**调用方 → 工具 → 规矩**。
#
# 抓到过一个真的:SHOP_TOOLS 一整包同时发给两个角色,于是任务助手
# (退款定因 / 客户合并 / 售后判责)手里有 forecast_growth、plan_for_event、
# get_wearer、get_capacity 四个工具,而这四个的用法规矩 TL09/TL10/TL12/TL13
# 全在工艺顾问那一侧 —— **工具给了,规矩没给**。
#
# 这比「工具没给」更危险:模型会用它,而且没有任何一句话告诉它怎么算用错。
# ⚠️ **按 `needs` 登记,不按 `scope` 登记。**
#
# 原来的条件是 `scope == "工具" and needs` —— 而 `scope` 默认是「铁律」,
# 于是新写的 TL23/TL24 **声明了依赖某个工具,却不被这条检查覆盖**:
# 咬合时把 TL23 从工坊池挪回任务池(工坊挂着 my_workorders 却拿不到规矩),
# **P6 一声不响**。
#
# 这就是这个项目钉过的那条:**注入没进检查的视野,「没红」不代表守得住。**
# 根子在 `needs` 和 `scope` 是两个独立字段,而它们本该联动 ——
# **一条声明了 needs 的规矩,天然就是工具级的**,不该再要求作者记得改 scope。
GOVERNED = {}                        # 工具名 → 管它的那条规矩
for _role, _r in prompts.all_rules(unique=True):
    if _r.needs:
        GOVERNED.setdefault(_r.needs[0], []).append((_role, _r.id))
_p6 = []
for nm, (role, have) in CALLERS.items():
    _, ids = prompts.assemble(role, have)
    got = set(ids)
    for t in sorted(have):
        owners = GOVERNED.get(t)
        if owners and not any(rid in got for _rl, rid in owners):
            _p6.append(f"{nm} 挂了 `{t}`,但没拿到管它的 {'/'.join(r for _, r in owners)}")
rule("P6", "挂了某个工具,就必须拿到那个工具的规矩", _p6,
     "「工具给了、规矩没给」比「工具没给」更危险 —— 模型会用它,"
     "而且没有任何一句话告诉它怎么算用错")

# ── P6 的前提:规矩按**名单**装,不按运行时取回了哪些装 ─────────────────
# 全能助手 10-23 起开了工具按需加载(ToolSearch 取回工具说明)。P6 是**静态**算的 ——
# 按名单 × needs 比对 —— 只有在「规矩启动时按名单全集装好」时才等于真相。
# 哪天有人把规矩改成跟着取回走(在钩子里现装、或按 ToolSearch 的结果装),
# 那一刻起 P6 的绿勾就不再守任何东西,而它照样绿。这一条就是盯那一刻的。
#   ① 运行时那一侧(guards.py 的钩子)不许装配提示词
#   ② sdk.py 里每一处 prompts.assemble 的第二个参数只许来自名单(_have / 研判工具 / 工具)
_GUARDS = open(os.path.join(ROOT, "agentsite", "guards.py"), encoding="utf-8").read()
_p6b = (["guards.py(运行时钩子)里装配了提示词 —— 规矩会跟着运行时走"]
        if re.search(r"\bassemble\(", _GUARDS) else [])
for _m in re.finditer(r"prompts\.assemble\(\s*[^,]+,\s*(.{0,80})", SDK):
    _arg = _m.group(1)
    if not re.match(r"(_have\(|\{t\.rsplit\(\"__\", 1\)\[-1\] for t in (研判工具|工具)\})", _arg):
        _p6b.append(f"sdk.py 装配规矩的名单不是来自角色名单:{_arg[:50]}")
rule("P6b", "规矩按名单启动时装配,不跟着运行时取回的工具走", _p6b,
     "按需加载之后,「挂了哪些工具」不再是启动时的事实;规矩一旦跟着运行时走,"
     "P6 这条静态检查就从那天起不守任何东西 —— 而它照样绿")

# ── P7:提示词里写的数字必须对得上库 ────────────────────────────────
# 栽过一次:TL02 写着「相容矩阵目前只录了 6%,遇到未定义是常态」——
# 而 derive_combo 后来把规则推导铺满了整张矩阵,**实际已经 100%**。
# 差了 16 倍,而且它是在**对模型说假话**:模型照着「未定义是常态」去准备,
# 而它一辈子也遇不到一个未定义格。
#
# 更坏的是这句话同时骗了评测:chat_eval 有两道题专测「未定义披露」,
# 测的是一个**不存在的状态**,还把答对的模型判成了错。
#
# 只查**能对上库的那几个数**,不做通用数字扫描 —— 通用扫描会把
# 「至少提前 2 小时」「±5cm」这类规则常量也扫进来,报一堆假的。
# **数法只能有一处** —— 直接问 api.kb_coverage(),不在这儿再写一套 SQL。
# 我第一版自己写了 `rule LIKE 'R%'`,数出 735,而 kb_coverage 报 2009,
# 两个数对不上。查下来是 kb_coverage 把 1274 格没有依据的(rule='—')
# 也算进了「规则推导」—— **同一个事实两种数法,必然漂**,这次漂出来的是
# 「63% 的格子没有依据」这个事实被藏住了。
_cov = api.kb_coverage()
FACTS = {
    "相容矩阵总格数": (_cov["总格数"], "格"),
    "人工确认格数":   (_cov["来源"].get("人工确认"), "格"),
    "规则推导格数":   (_cov["来源"].get("规则推导"), "格"),
    "默认放行格数":   (_cov["来源"].get("默认放行(无依据)"), "格"),
}
_ALL = "\n".join(r.text for _, r in prompts.all_rules(unique=True))
_p7 = [f"{k} 库里是 {v}({u}),提示词里没有这个数"
       for k, (v, u) in FACTS.items() if v is not None and str(v) not in _ALL]
rule("P7", "提示词里引用的库内数字必须对得上", _p7,
     "提示词写「只录了 6%」而实际 100%,是**在对模型说假话** —— "
     "它会照着一个不存在的世界去准备,而且这句话还会顺手骗过评测")

# ── P4:稳定编号不得重复 ────────────────────────────────────────────
# 去重版:同一条规矩被多个角色复用是**设计**,不是编号撞车
ids = [r.id for _, r in prompts.all_rules(unique=True)]
dup = [f"{i} 出现 {ids.count(i)} 次" for i in sorted(set(ids)) if ids.count(i) > 1]
rule("P4", "稳定编号唯一", dup, "编号撞了,外部文档引用的就不知道是哪一条")

# ── P10:差评处理方式的名单,不许在「对模型说的话」里手抄 ─────────────────
#
# ⚠️⚠️ **2026-10-13 的事故换来的。** 那天「免运费」进了 `knowledge/rating.处理方式`
# (用户拍的),而 `backend/api.py` 里**三处**手抄的「只认这五种」名单没跟上。
# 后果不是报错,是**模型照描述把「免运费」当成自己造的词不敢填** ——
# **判定层放行,说明层拦着**,而两层分别看都是对的。
#
# 📌 被改掉的那段函数注释长这样:
#     way 处理方式,**只认登记过的那五种**(只回访 / 免次改衣 / ...)。
#         判定在 `knowledge/rating.处理方式能不能用`,**这儿不抄**。
# **「这儿不抄」这句话,就写在抄了的那一行旁边。**
# > 一条写着「我不抄」的注释,和一份真的没抄的代码,在那一行上长得一模一样。
#
# ⚠️⚠️ **这条判据不能写成「描述和枚举对得上」** —— 描述改成现拼之后,
# 那就是拿枚举去比枚举,**同源,恒真**(这个项目的「同源谬误」那条教训)。
# 它验的是**源码里还有没有手抄的名单**:一个字符串字面量里同时出现 3 种以上
# 处理方式名,那就是一份手抄件 —— 而**手抄件不会自己跟着枚举变**。
#
# ⚠️⚠️ **这条判据第一版自己就失效过一次**:正则写成 `"(...){20,}"`,
# 而它**不懂 Python 语法** —— 从一个引号一路匹配到下一个,**跨过行尾和注释**。
# 于是写在 `#` 注释里的教训记录(里头原样引了那份旧名单)被当成了「对模型说的话」。
# 修法是把换行加进排除集:单行字面量里不可能有裸换行。
# > **一条扫源码的判据,和一条真的读懂了源码的判据,在「它报了几条」上长得一模一样。**
#
# ⚠️ 盲区(写出来,别当它守住了全部):
#   · 只扫**对模型说话**的那几个地方(api.py / prompts.py / mcp/),
#     别处手抄了扫不到;
#   · 只认 3 种以上挤在同一个字面量里的。抄两种的躲得过去 ——
#     而两种也够造出「说明层拦着」那个后果。门槛定 3 是为了不误伤
#     「出钱的那两种」这类**本来就该点名**的说法。
_方式 = [x for x in RT方式.处理方式 if len(x) >= 3]
_对模型说的 = [os.path.join(ROOT, "backend", "api.py"),
              os.path.join(ROOT, "prompts.py")]
for _d, _dn, _fn in os.walk(os.path.join(ROOT, "mcp")):
    _dn[:] = [x for x in _dn if x not in ("__pycache__", ".venv")]
    _对模型说的 += [os.path.join(_d, f) for f in _fn if f.endswith(".py")]
_抄 = []
for _fp in _对模型说的:
    if not os.path.exists(_fp):
        continue
    _src = open(_fp, encoding="utf-8").read()
    for _m in re.finditer(r'"((?:[^"\\\n]|\\.){20,})"', _src):
        _有 = [w for w in _方式 if w in _m.group(1)]
        if len(_有) >= 3:
            _抄.append(f"{os.path.relpath(_fp, ROOT)}:{_有} 挤在同一个字面量里")
rule("P10", "差评处理方式的名单不许在对模型说的话里手抄", _抄,
     "手抄的名单不会跟着枚举变 —— 枚举加一档,模型会把它当成自己造的词不敢填。"
     "改成从 `knowledge/rating.处理方式` 现拼")

# ── P11:也不许用**数量或位置**指代处理方式 ──────────────────────────────
#
# ⚠️ 这条和 P10 是同族,而 P10 **抓不到它**:P10 抓手抄的**名单**,
# 这条抓手抄的**数量和位置**。2026-10-13 扫出来的实例:
#   · `prompts.py` 的 TK14:「**后三种**要出钱,必须给批准人」
#     —— 而出钱的只有**两种**。「优惠券」被拍掉那天这句话没跟上,
#     照它做,模型会给「送保养」也去要批准人。
#   · `backend/api.py`:「**后两种**是要出钱的……**前三种**不要填 approved_by」
#
# > **一个「位置指代」和一个「点名」,在读起来通顺这件事上长得一模一样,
# > 而只有点名的那个会跟着枚举变。**
#
# ⚠️ 盲区:它只抓**和处理方式名挤在同一个字面量里**的位置指代。
# 别处说「后三种」扫不到 —— 而那也可能是在说别的东西,不该一概判红。
_位置 = re.compile(r"(?:前|后|头|末)(?:两|三|四|五|六|七|八|九|十|\d+)种"
                  r"|(?:两|三|四|五|六|七|八|九|十|\d+)种之一")
_指代 = []
for _fp in _对模型说的:
    if not os.path.exists(_fp):
        continue
    _src = open(_fp, encoding="utf-8").read()
    for _m in re.finditer(r'"((?:[^"\\\n]|\\.){20,})"', _src):
        if not any(w in _m.group(1) for w in _方式):
            continue
        for _h in _位置.finditer(_m.group(1)):
            _指代.append(f"{os.path.relpath(_fp, ROOT)}:「{_h.group(0)}」"
                        f"和处理方式名写在同一句里")
rule("P11", "不许用数量或位置指代处理方式(「后三种要出钱」那种)", _指代,
     "枚举一改,位置和数量都漂,而那句话读起来照旧通顺 —— 改成点名出钱的那几种")

# ── P9:源码里定义了的规矩,必须真的被某个角色装上 ────────────────────
# ⚠️ **这一条是补票买的。** 2026-09-24 加的「不让价,只让东西」那条铁律,
# 写在了 `KB_RULES = [...]` 的 `]` **之后** —— 语法完全合法,它只是一个
# **值被丢掉的表达式**,于是这条规矩**一天都没装到模型上**。
# 09-25 真跑评测才发现:模型张口就说「我们确实有调整空间」。
# 闸(g23)一直在工作,规矩一直没送到 —— 而两者在代码里都「写着」。
#
# P4 查编号撞车、P8 查装配有没有接到 run() 上,**都看不见这一类**:
# 一条没进任何列表的规矩,既不参与编号比较,也不在装配结果里,
# **它在源码里和一条正常的规矩长得一模一样。**
_定义了 = set(re.findall(r'Rule\(\s*"([A-Z]{2}\d+)"', open(
    os.path.join(ROOT, "prompts.py"), encoding="utf-8").read()))
_装上了 = {r.id for _, r in prompts.all_rules()}
_孤儿 = sorted(_定义了 - _装上了)
rule("P9", "定义了的规矩都被某个角色装上了", _孤儿,
     "**写在列表的 `]` 之后就是一个值被丢掉的表达式** —— 规矩在源码里躺着,"
     "模型一次都没收到,而两种情况在代码里长得一模一样")

# ── P8:装配出来的提示词必须真的接到模型上 ──────────────────────────
# **P3 验的是「装得出来」,P8 验的是「装上了」** —— 这是两件事,
# 而这个项目刚在财务角色上栽了一次:`prompts.py` 里 FINANCE_HEAD/FINANCE_RULES/TL24
# 全写好了,`CALLERS` 里也登记了,P3/P6 全绿 ——
# 但 `sdk.py` 的 `_SYS` 那张表漏了 `finance` 一行,
# 而取用处写的是 `_SYS.get(kind, SYS_ALL)`,**静默回落到全能助手**。
# 于是那套财务提示词一个字都没进过模型,评测还过了 5/7。
#
# 「一份没有被引用的主数据,和一份不存在的主数据,业务效果一样」——
# 提示词也是主数据。这条就是查它被引用了没有。
_SYS_KEYS = set(re.findall(r'"(\w+)":\s*SYS_\w+', SDK))
_断了 = [f"{role}(CALLERS 里登记了,但 sdk._SYS 里没有这一行 —— "
        f"run() 会静默用全能助手的规矩)"
        for nm, (role, _) in CALLERS.items() if "sdk" in nm and role not in _SYS_KEYS]
# 反向:`.get(kind, 默认)` 本身就是这个 bug 的载体 —— 漏配时它不报错。
# ⚠️ **扫代码,不扫文本**:第一版直接 grep 源码,当场撞上我自己写在
# `_SYS` 上方那条「原来写的是 `_SYS.get(kind, SYS_ALL)`」的注释 ——
# 注释里解释这个坑,反而被判成还有这个坑。**判据贴着文案就会这样。**
# 用 AST 找真的属性调用,注释和字符串都不算。
import ast
_真的用了get = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
    and n.func.value.id == "_SYS"
    for n in ast.walk(ast.parse(SDK)))
if _真的用了get:
    _断了.append("sdk.py 用 `_SYS.get(kind, 默认)` 取提示词 —— "
               "漏配一个角色时它不会报错,只会悄悄降级成全能助手")
rule("P8", "装配出来的提示词必须真的接到 run() 上", _断了,
     "**装得出来 ≠ 装上了**。提示词也是主数据,没被引用的主数据"
     "和不存在的一样 —— 而它看起来一直好好地躺在源码里")

print("\n" + "=" * 84)
if bad:
    print(f"❌ {len(bad)} 条没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    sys.exit(1)
print(f"✅ 提示词单一源头(P1–P8)· 共 {len(ids)} 条铁律,{len(CALLERS)} 个调用方")
