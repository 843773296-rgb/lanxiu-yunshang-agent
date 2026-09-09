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
def rule(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    for r in rows[:6]: print(f"        · {r}")
    if rows: bad.append((no, why, len(rows)))

# ── P1:唯一源头 ────────────────────────────────────────────────────
# 角色开场白拼出来,**不写成一个完整字面量** —— 否则这个文件自己会被扫中。
# (密钥扫描在同一个坑里栽过四次:规则字符串写进被扫文件,自己匹配自己。)
OPEN = "你是澜绣" + "云裳"
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
KBSET = {t["name"] for t in api.KB_SCHEMAS}
CALLERS = {
    "工作站·全能助手(sdk)":   ("all",  KB | KBONLY | WORK | TASK | TASKONLY | SHOP | {"图片"}),
    "工作站·工艺顾问(sdk)":   ("kb",   KB | KBONLY | SHOP | {"图片"}),
    "工作站·工坊排产(sdk)":   ("workshop", WORK),
    "工作站·任务助手(sdk)":   ("task", TASK | TASKONLY | SHOP),
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
GOVERNED = {}                        # 工具名 → 管它的那条规矩
for _role, _r in prompts.all_rules(unique=True):
    if _r.scope == "工具" and _r.needs:
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

print("\n" + "=" * 84)
if bad:
    print(f"❌ {len(bad)} 条没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    sys.exit(1)
print(f"✅ 提示词单一源头(P1–P7)· 共 {len(ids)} 条铁律,{len(CALLERS)} 个调用方")
