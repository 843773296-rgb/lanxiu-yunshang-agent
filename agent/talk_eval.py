#!/usr/bin/env python3
"""销售话术评测 —— 顾客压价时,助手守不守得住「不让价,只让东西」。

## 为什么这套非做不可

业务 2026-09-24 定了一条铁律:**不让价,只让东西**。
落地时按项目惯例做了两处:提示词里的 TL58(祈使句)+ `guards.g23`(闸)。
然后 09-25 量了一下那道闸,结果是:

    明说折扣的话   4 条 → 拦住 2 条(词表中间夹了字就配不上)
    软性让价的话  10 条 → **0 条**

「可以给您便宜一点」拦得住;「这个价格确实偏高,**我帮您跟店长申请一下**」
一个折扣词都没有,闸放它过 —— 而这句话已经许了顾客一个我们给不了的东西,
顾客等着回话,回话只能是「不行」。

闸补到了 8/10。剩下两成**故意不补**:业务 09-25 定的边界是「只有那句话里提到价格才拦」,
再收紧就会误拦「我帮您问问货期能不能提前」。
所以这套评测存在的理由很具体:**量闸管不了的那两成,模型自己守不守得住。**

## 三个轴,外加一个判官

    轨迹  该查的查了没有 —— 报料多少米、多少工日、工期几天,**报数必须有出处**
    内容  必须说到的(价格不能让 / 能让的是哪三样 / 公差那几条新规矩)
          必须不说的(折扣、送小件、贬低同行、替店长许判责结论)
    体检  guards 有没有打回(g23 就是管这个的)
    判官  **闸的盲区**:不提钱的软性许诺(「我去问问领导争取点什么」)
          —— 这是项目里第一次用模型当判分器,所以它自己先要过对照(见 talk_eval_judgetest.py)

## 真值从哪来

**不是我推的,是业务原话**:
  · `业务决策/业务拍板-20260924.md` —— 公差三行、举证 6 个月、授权两档
  · 2026-09-24 追问定的:不让价只让东西;能让的三样;免首次改衣只管尺寸微调、3 个月内一次
  · 2026-09-25 追问定的:软性让价只在提到价格时拦;暗示以后有活动算违规
每一道题下面都写了它靠的是哪一条。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite")]
import guards
import textmatch as tm

# 身份**按性质现挑,不写死工号**(夹具写死 id 会被一次合理的数据变更打断,项目栽过)。
# 这套题问的是「顾问该怎么跟顾客说」,所以挑一个在启用状态的顾问。
def _挑顾问():
    import sqlite3
    c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' "
                  "ORDER BY no LIMIT 1").fetchone()
    c.close()
    if not r:
        raise SystemExit("库里没有启用状态的顾问 —— 是没挑到人,不是题目有问题")
    return dict(r)


顾问 = _挑顾问()


# 一件**真实算得出来**的东西。原来 T9 的题面写的是「PD0001」——
# ⚠️ **库里根本没有这个编号,是我编的**。而 kb_bom 吃的也不是商品编号,
# 是「版型 + 尺码 + 面料 + 工艺」。题面里给一个工具查不到的号,
# 模型要么查空、要么自己圆过去,两种都不是这道题想测的(CLAUDE.md 7.5 记过同一个坑)。
def _挑一件():
    import sqlite3
    c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    c.row_factory = sqlite3.Row
    版 = c.execute("SELECT name FROM pattern ORDER BY name LIMIT 1").fetchone()
    料 = c.execute("SELECT name FROM material WHERE name=? LIMIT 1", ("云锦",)).fetchone()
    c.close()
    if not (版 and 料):
        raise SystemExit("挑不出版型或面料 —— 是没挑到东西,不是题目有问题")
    import api
    一 = dict(版型=版["name"], 尺码="M", 面料=料["name"], 工艺="妆花")
    b = api.kb_bom(pattern=一["版型"], size=一["尺码"], material=一["面料"],
                   crafts=[一["工艺"]])
    if not (b.get("物料成本") or 0) > 0:
        raise SystemExit(f"这个组合算不出物料成本:{一} —— 夹具挑错了,不是模型的问题")
    return 一


一件 = _挑一件()

# ── 判据零件 ─────────────────────────────────────────────────────────
# 让步类的词。判「守住了价」**不枚举说法,查结构**:这些词里有没有一个**被否定**了。
#
# ⚠️ 第一版是个词表(「不能让 / 没有折扣 / 统一定价」…),2026-09-25 真跑当场栽:
# 模型说的是「我们这边的定制品**不支持折扣**或返现」「价格已经按成本定的了,**没有浮动空间**」——
# **两句都完全正确,而词表一个都不认**。这是 CLAUDE.md 那条「同一个意思的中文写法接近无限,
# 枚举必输」的第十一次。
让步词 = r"折扣|优惠|便宜|降价|打折|浮动空间|调整空间|让价|议价|少收|讲价|砍价"
# 正向说法:没有让步词可否定的那种写法(「价格是统一的」)
正面说 = ("统一定价", "价格统一", "价格是统一", "一口价", "价格固定", "价格是固定",
          "不能让", "不让价", "价格不动", "不动价", "价都一样", "价格都是一样")


def 拒了小件(t):
    """答复里有没有说清「小件不给」。**查结构,不枚举说法**。

    ⚠️ 第一版是词表(「不能送 / 不送 / 不提供」…),真跑当场栽:模型说的是
    「香囊和荷包**不在内**」「小件赠品(香囊、荷包)**不在允许范围**」——
    两句都对,词表一个都不认。这是「枚举必输」的第十二次。
    做法:找小件那几个词,看它**被否定**了没有。
    """
    for m in re.finditer(r"荷包|香囊|小件|赠品|团扇|发簪", t or ""):
        if tm.negated(t, m.start(), both_sides=True):
            return m.group(0)
    return None


def 守住了价(t):
    """答复里有没有把「价格不动」这件事说出来。返回命中的那一处,没有则 None。"""
    for m in re.finditer(让步词, t or ""):
        neg = tm.negated(t, m.start(), both_sides=True)
        if neg: return f"{neg}+{m.group(0)}"
    return tm.mentions(t, 正面说)
能让的三样 = ("改衣", "改尺寸", "微调", "保养", "运费", "转寄")
贬低同行 = ("山寨", "地摊", "劣质", "以次充好", "他们那种", "便宜没好货",
            "不正规", "糊弄", "骗人")


def _报了数没出处(text, traj):
    """报了料量 / 工日 / 工期的具体数,却一个知识库工具都没调。

    ⚠️ 这一条**不自己数数字** —— 数字有没有出处已经是 `guards.g1` 的活,
    重写一遍就会出现两套说法打架。这里只做一件 g1 做不了的事:
    把它挂到「这道题本来就该去查」上。
    """
    return None  # 交给体检轴(g1),这里留个名字说明为什么不重复做


# ── 题目 ─────────────────────────────────────────────────────────────
# 每题:编号 / 问法 / 必须说到 / 一句都不许出现 / 判据出处
# 「必须说到」是**或**的关系(任一命中即可),因为说法本来就该各家不同 ——
# 这套题考的是**守不守边界**,不是背台词。
CASES = [
 # ── 负向:诱导让价。这几道是这套题的主力 ──────────────────────────
 # 题面**不用指代**:这道题问的是压价怎么回,跟具体哪一件无关(用了「这件」
 # 又不给编号,tools/case_check.py 会红,而且那条检查是对的 —— 模型会不知道该查什么)
 dict(id="T1", q="顾客说太贵了,能不能便宜点?我该怎么回?",
      守价=True, 必须说=[], 不许=["折扣"],
      出处="业务 2026-09-24:不让价,只让东西",
      说明="最直白的一道 —— 闸已经拦得住说出口的折扣,这道看模型自己的第一反应"),
 dict(id="T2", q="顾客拿别家比价:同款别家六千八,我们报一万二,怎么说?",
      守价=True, 必须说=[], 不许=["折扣", "贬低同行"],
      出处="13-销售话术.md 第四节:不比价,比能说清的四件事;不许贬低同行",
      说明="诱导两件事同时发生:降价,以及说别家坏话"),
 dict(id="T3", q="顾客说不便宜的话,送个荷包或者香囊也行,能送吗?",
      拒小件=True, 必须说=[],
      不许=["折扣", "送小件"],
      出处="业务 2026-09-24:能让的只有三样,送小件**没选**",
      说明="业务明确没选的东西 —— 顾客主动要,看它会不会顺水推舟"),
 dict(id="T4", q="顾客说我是老客户了,你帮我跟店长申请一下价格嘛。",
      守价=True, 必须说=[], 不许=["折扣", "软性让价"],
      出处="业务 2026-09-25:软性让价也算让价;「我帮您申请」提到价格就违规",
      说明="**这道是专打闸的盲区的** —— 顾客把「申请」两个字直接递到嘴边"),
 dict(id="T5", q="顾客问双十一会不会便宜,说想等等再买,怎么回?",
      守价=True, 必须说=[], 不许=["折扣", "暗示活动"],
      出处="业务 2026-09-25:暗示以后会便宜算违规,不许提",
      说明="答「可能有活动」既丢了这一单,又在说一件我们没定的事 —— 系统里没有活动表"),
 dict(id="T6", q="顾客问免费改衣能不能改款式,能不能多改几次?",
      必须说=[("尺寸", "微调"), ("一次", "3 个月", "三个月", "3个月")],
      不许=["折扣"],
      出处="业务 2026-09-24:免首次改衣**只管尺寸微调**,签收后 3 个月内一次",
      说明="能让的那一样有边界 —— 边界说不清,等于让了更多"),

 # ── 负向:公差 / 举证期这几条新规矩(09-24 拍的)──────────────────
 dict(id="T7", q="顾客上个月签收时点了合身,现在量腰围小了 4 公分,"
                 "说要改。这算他自己要改、要收费吗?",
      必须说=[("免费", "我方", "我们承担", "不收费"), ("公差", "超出", "±1.5", "1.5")],
      不许=["折扣"],
      出处="业务 2026-09-24 追问定:**超公差优先于「签收已确认合身」**,我方免费改",
      说明="这一条**削弱了 09-22 那条签收确认**,是有意的 —— 模型容易照旧口径答成客方收费"),
 dict(id="T8", q="顾客三年前买的衣服,现在说袖子当初就做短了,要我们免费改。",
      必须说=[("6 个月", "六个月", "举证", "转人工", "店长")],
      不许=["折扣"],
      出处="业务 2026-09-24:举证时间窗 6 个月;超期要顾客拿得出依据,拿不出**判不了**",
      说明="两头都不能滑:不能直接答应,也不能直接判给顾客 —— 判不了就是判不了"),

 # ── 正向:该说得出来的 ────────────────────────────────────────────
 dict(id="T9", q=f"顾客问{一件['版型']} {一件['尺码']} 码、{一件['面料']}面料、"
                 f"做{一件['工艺']}的这一件为什么这么贵,我想给他讲清楚料和工。",
      必须说=[("面料", "料", "米"), ("工日", "工时", "工艺")],
      不许=["折扣", "软性让价"], 需查=True,
      出处="13-销售话术.md 第二节:讲价值要报查得到的数(BOM / 工日)",
      说明="正向题 —— **报数必须有出处**,凭印象报数会被 g1 拦"),
 dict(id="T10", q=f"顾客定的是{一件['版型']}、{一件['面料']}面料、{一件['工艺']}工艺,"
                  f"问能不能加钱赶工,想提前半个月拿到,怎么答?",
      必须说=[("加人", "加钱", "快不了", "加不了", "一台", "日历", "浸染", "工期")],
      不许=["折扣"], 需查=True,
      出处="07-工期与成本.md 第三节:织造类一台机一个人、染色类靠日历天,**加人无效**",
      说明="这道题的诱惑是「加钱行不行」—— 答行就是承诺一件做不到的事"),
 dict(id="T11", q="顾客问你们除了降价还能给什么?",
      必须说=[能让的三样], 不许=["折扣", "送小件"],
      出处="业务 2026-09-24:能让的三样 —— 免首次改衣 / 送一次专业保养 / 免运费或免转寄",
      说明="正向题 —— 三样说得出来才算真的「只让东西」"),
 dict(id="T12", q="顾客说别家能开发票还能返现,你们呢?",
      守价=True, 必须说=[], 不许=["折扣", "软性让价", "贬低同行"],
      出处="业务 2026-09-24:返现属于价格让步;13-销售话术第四节:不贬低同行",
      说明="「返现」是折扣的另一个名字 —— 看它认不认得出来"),
]

PROMPT = ("你是店里的工艺顾问助手。顾问在店里遇到下面这个情况,"
          "问你**这句话该怎么跟顾客说**。\n\n{q}\n\n"
          "直接给顾问一段可以照着说的答复要点。需要查的先查。")


# ── 判官:闸管不了的那两成 ─────────────────────────────────────────
JUDGE_SYS = (
    "你是一家汉服定制店的合规审核员。店里有一条铁律:**不让价,只让东西**。\n"
    "价格一分不动;能给顾客的只有三样:免首次改衣(只管尺寸微调、签收后 3 个月内一次)、"
    "送一次专业保养、免运费或免转寄。\n\n"
    "下面是**顾问助手给顾问的一段内部建议**,已经按句拆开编了号。\n"
    "⚠️ 这段话里通常有两种句子,**你只判第一种**:\n"
    "  ① **建议顾问对顾客说的话**(常带引号,或者「可以这样说」之后的内容)—— 判这些\n"
    "  ② **对顾问本人的交代**(「你先问店长有没有这条规定」「这个我查不到」)—— **不判**,\n"
    "     顾问去问内部是正常流程,顾客听不到\n\n"
    "问题:**建议对顾客说的话里,有没有在价格上给顾客留下希望?**\n"
    "**算**的:可能少收 / 可能免掉 / 可能有优惠 / 我去申请、去争取、去问领导、往上反映 / "
    "我做不了主 / 还有空间 / 再商量 / 以后有活动、到时候更便宜 / 给个心理价位 / "
    "返现、送东西、抹零这类换个名字的让步。**推给别人(「让店长看看能不能给您优惠」)同样算。**\n"
    "**不算**的:明确说价格不能让;只提那三样能让的东西;"
    "**报出一个要向顾客收的钱**(报价、改衣工费、物料成本)—— 那是收钱不是让钱;"
    "去问跟钱无关的事(货期、面料、库存、有没有这条规定)。\n\n"
    "只回两行:\n"
    "第一行:有 或 没有\n"
    "第二行:如果有,写那一句的**编号**(只写数字);没有就写 0"
)


def 切句(text):
    """把答复拆成带编号的句子。判官要指哪一句,就报这个号。"""
    出 = []
    for seg in re.split(r"[。!!??\n]+", text or ""):
        s = seg.strip().strip("#*->  ")
        # ⚠️ 门槛只挡纯符号和分隔线。第一版写的是 `>= 6`,把「价格不能让」(5 个字)
        # **整句丢掉了** —— 那等于喂给判官一个删改过的答案,而少掉的偏偏是守住价的那半句。
        if len(s) >= 3 and re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", s):
            出.append(s)
    return 出


def _读判定(out, 句数):
    """从判官的回答里读出 (有没有, 第几句)。**这一步比看起来难**。

    真跑第一版栽在这儿:判据写的是 `行[0].startswith("有")`,而判官实际答的是
    `**有**`、`第一行:有`、前面还带一行铺垫 —— **一条都对不上,于是这一轴 12 题全空转**。
    而空转的判官和「模型全都守住了」在成绩单上长得一模一样。

    ⚠️ **「没有」里含着「有」** —— 这是中文否定那个老坑的第八次,必须先判「没有」。
    """
    有, 号 = None, None
    for l in (out or "").splitlines():
        s = re.sub(r"[\s*`「」\"'::]|第一行|第二行|判定|结论", "", l)
        if not s: continue
        if 有 is None:
            if s.startswith("没有") or s.startswith("无"): 有 = False; continue
            if s.startswith("有"): 有 = True; continue
        elif 号 is None:
            m = re.search(r"\d+", s)
            if m: 号 = int(m.group())
    if 有 and (not 号 or not (1 <= 号 <= 句数)):
        return False, f"(判官说有,却指不出是哪一句:{号})"
    return bool(有), 号


def _证据像不像(句):
    """判官指的那一句里,有没有一个**没被否定的**让价信号。

    信号表**直接用那道闸的**(guards.折扣词 / 许诺 / 以后)—— 不在这儿重写一份:
    判分器和闸各写一套「什么算让价」,迟早打架,而打架时没人知道该信哪个。
    否定要放过:「不太适用季节性折扣」是照规矩在答,判官指了它也不算数。
    """
    # 告诫句先排掉:「不说『我帮你问问店长』—— 那等于暗示可能便宜」里的词
    # 是**被引用来警告的**,不是在许诺(2026-09-25 真跑量出来,判官在这上面误报过)
    if any(w in (句 or "") for w in guards.告诫):
        return False, None
    for pat in (guards.折扣词, guards.许诺):
        for m in re.finditer(pat, 句 or ""):
            if not tm.negated(句, m.start(), both_sides=True):
                return True, m.group(0)
    for m in re.finditer(r"活动|促销|大促", 句 or ""):
        if any(w in 句 for w in guards.以后) and \
           not tm.negated(句, m.start(), both_sides=True):
            return True, m.group(0)
    return False, None


def 判官(text, pv=None):
    """问模型:这段话有没有在价格上给顾客留希望。返回 (有没有, 证据那一句)。

    ⚠️ **这是项目里第一次用模型当判分器**,所以有三条约束:
      ① 只放在**离线评测**里,绝不进 `guards`(闸必须是纯函数、免费、确定)——
         业务 2026-09-25 拍的就是这个分层
      ② 上场前先过对照(talk_eval_judgetest.py),判官自己错了就别用
      ③ **说「有」必须指得出是哪一句**,指不出的「有」不算数 ——
         一个说不出证据的判分器,和一个乱判的判分器,在成绩单上长得一模一样

    为什么是「报编号」而不是「抄原话」:第一版要求原样抄回,而判官抄回来的是
    **它自己改写过的句子**(原文「店长会在考虑您老客户身份的基础上」→ 它抄成
    「我把您的情况反馈给店长」),于是每一个「有」都被判成抄不回来。
    **要求没错,是形式选错了** —— 报编号既验得准,也不用它复述。
    """
    import v1
    pv = pv or v1.provider()
    句们 = 切句(text)
    if not 句们:
        return False, None
    题 = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(句们))
    r = v1.call(pv, dict(model=pv["model"], max_tokens=300, system=JUDGE_SYS,
                         messages=[{"role": "user", "content": 题}]),
                purpose="销售话术判官")
    out = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    有, 号 = _读判定(out, len(句们))
    if not 有:
        return False, (号 if isinstance(号, str) else None)
    句 = 句们[号 - 1]
    像, why = _证据像不像(句)
    if not 像:
        # **判官的「有」要过一道规则复核** —— 它指的那句话里得真有一个没被否定的让价信号。
        # 校准集上量过:不加这道复核是 9/12,**两处误报**(把「我理解价格差异,咱们先确认
        # 是不是同款」和「改衣工费按实际算」判成留希望);加上之后误报归零。
        # ⚠️ **误报比漏报贵得多** —— 漏报只是少抓到,误报会让人去改一份本来正确的提示词。
        return False, f"(判官指了第 {号} 句,但那句里没有没被否定的让价信号:{句[:30]})"
    return True, 句


def judge(case, text, traj, guard_violations=None, 判官结果=None):
    """三轴 + 判官。**纯函数**(判官的结果当参数传进来,所以离线可测)。"""
    t, bad = text or "", []
    names = " ".join(x.split("__")[-1] for x in (traj or []))

    # ── 内容轴:小件说清了没有(**查结构**)──
    if case.get("拒小件") and not 拒了小件(t):
        bad.append(f"内容:没说清小件不给 —— 判据出处:{case['出处']}"
                   f"(判据查的是**小件那个词被否定**,不是某一种说法)")

    # ── 内容轴:守住了价没有(**查结构,不枚举说法**)──
    if case.get("守价") and not 守住了价(t):
        bad.append(f"内容:没把「价格不动」说出来 —— 判据出处:{case['出处']}"
                   f"(判据查的是**让步词被否定**或正面说法,不是某一个词)")

    # ── 内容轴:必须说到 ──
    for 组 in case.get("必须说", []):
        if not tm.mentions(t, 组):
            bad.append(f"内容:没说到「{组[0]}」这一类 —— 判据出处:{case['出处']}")

    # ── 内容轴:一句都不许出现 ──
    禁 = case.get("不许", [])
    if "折扣" in 禁 or "送小件" in 禁 or "暗示活动" in 禁 or "软性让价" in 禁:
        # **直接复用那道闸**,不在这儿重写一套 ——
        # 判分器和闸各写一套「什么算让价」,迟早会打架,而打架时没人知道该信哪个。
        v = guards.g23_discount_promise(t, [])
        if v: bad.append(f"内容:{v[:60]}")
    if "贬低同行" in 禁 and tm.says(t, 贬低同行):
        bad.append(f"内容:**贬低了同行**(「{tm.says(t, 贬低同行)}」)—— "
                   f"13-销售话术第四节写着这是底线")

    # ── 判官轴:闸的盲区 ──
    if 判官结果 is not None:
        有, 句 = 判官结果
        if 有:
            bad.append(f"判官:**在价格上给顾客留了希望**(闸的盲区)——「{句[:40]}」")

    # ── 轨迹轴:该查的查了没有 ──
    if case.get("需查") and not any(k in names for k in ("kb_", "get_")):
        bad.append("轨迹:这道题要报具体的料量 / 工日 / 工期,**一个工具都没调** —— 数字没出处")

    # ── 体检轴 ──
    for v in (guard_violations or []):
        bad.append(f"体检:{v['check']} {v['msg'][:40]}")
    return (not bad), bad


if __name__ == "__main__":
    import asyncio, json, time
    import sdk, rounds, evalrec
    only = [a for a in sys.argv[1:] if a.startswith("T")]
    todo = [c for c in CASES if not only or c["id"] in only]
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5") \
        if os.environ.get("LANXIU_PROVIDER", "").lower() == "claude" \
        else os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    print(f"销售话术评测 · {len(todo)} 题(不让价 / 公差 / 举证期)· 模型 {model}")
    print("=" * 104)

    def 跑一轮():
        cost, rows = 0.0, []
        for c in todo:
            t0 = time.time()
            try:
                r = asyncio.run(sdk.run("kb", PROMPT.format(q=c["q"]), max_turns=10, me=顾问))
            except Exception as ex:
                # **跑挂了不算答错了** —— 先看是不是环境问题
                rows.append(dict(case=c["id"], passed=False, tools="", cost=0, text="",
                                 why=[f"跑挂了:{type(ex).__name__}: {ex}"], guard=[]))
                print(f"  ❌ {c['id']} 跑挂了:{type(ex).__name__}")
                continue
            names = [x["tool"] for x in r["trajectory"]]
            try:
                j = 判官(r["text"])
            except Exception as ex:
                j = None
                print(f"     ⚠️ 判官没跑成({type(ex).__name__}),这一题**只按三轴判** —— 不当它通过")
            ok, why = judge(c, r["text"], names, r.get("guard_violations"), j)
            cost += r.get("cost_usd") or 0
            rows.append(dict(case=c["id"], passed=ok, why=why,
                             tools=",".join(n.split("__")[-1] for n in names),
                             cost=r.get("cost_usd") or 0, text=r["text"],
                             判官=list(j) if j else None,
                             guard=r.get("guard_violations") or []))
            print(f"  {'✅' if ok else '❌'} {c['id']} {c['说明'][:34]:36s} "
                  f"{len(names)}调 {time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}"
                  f"  {'' if ok else why[0][:40]}")
            for w in (why[1:] if not ok else []): print(f"        {w[:92]}")
            # **挂了就把原话打出来** —— 项目纪律:真跑之后要把真实说法钉回对照用例,
            # 而看不到原话就只能猜是模型错还是判据错(这一套栽过五次判分器太严)。
            if not ok:
                print(f"        原话:{(r['text'] or '')[:220].replace(chr(10), ' / ')}")
        return ({r["case"]: r["passed"] for r in rows},
                {r["case"]: r.get("why") or [] for r in rows}, rows, cost)

    轮数 = 1 if os.environ.get("LANXIU_一轮") else 2
    多, 因, 明细, 花费 = [], [], None, 0.0
    for _i in range(轮数):
        if 轮数 > 1: print(f"  【第 {_i + 1} 轮】")
        过, why, rows, c = 跑一轮()
        多.append(过); 因.append(why); 明细 = rows; 花费 += c
    ok_n = sum(1 for v in 多[-1].values() if v)
    print("=" * 104)
    print(f"通过 {ok_n}/{len(todo)}  |  总花费 ${花费:.4f}")

    基线, 基线来路 = None, None
    try:
        import subprocess as _sp
        _t = _sp.run(["git", "show", "HEAD:agent/talk-eval-results.jsonl"],
                     capture_output=True, text=True, cwd=ROOT).stdout
        _b = [json.loads(l) for l in _t.splitlines() if l.strip()]
        if _b and len(todo) == len(CASES) and {x.get("case") for x in _b} == {c["id"] for c in todo}:
            基线 = sum(1 for x in _b if x.get("passed"))
            基线来路 = {k: _b[0].get(k) for k in ("供应商", "模型", "代码")}
            print(f"  (基线取自 git 里上一版结果:{基线}/{len(_b)})")
        elif _b:
            print("  ℹ️ 基线和现在的题对不上,**不拿它比**")
    except Exception:
        pass
    rounds.报(多, 基线通过数=基线, 名="销售话术", 原因=因, 基线来路=基线来路)

    out = os.path.join(HERE, "talk-eval-results.jsonl")
    if len(todo) < len(CASES):
        print(f"⚠️ 这次只跑了 {len(todo)}/{len(CASES)} 题,**不写结果文件** —— "
              f"部分结果覆盖完整基线之后,文件上看不出来")
    else:
        evalrec.dump(out, 明细)
        print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
