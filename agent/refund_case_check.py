#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三条退款研判题的**题面材料**判据 —— 遮住了、没遮过头、基准对得上、咬合会红。

`DQ9001` 在真库上**已经被走完闭环**(研判已采纳 → 财务登记已退 → 办结),
而它考的是「AI 会不会查支付流水」。所以题面材料必须是**出事时**的样子 ——
否则材料里直接写着「已退」,这道题谁都答得对。

用户 2026-10-16 选了「现取 + 遮蔽」这条路,**代价是知道的**:
「漏遮一处就送分,而且分数变好看没人查」。这个文件是那条代价的对手。

## 五关各答一个不同的问题

    ① 遮住了吗          —— 至少遮住一处(一处也没遮和遮干净了,在返回值上长得一模一样)
    ② 遮过头了吗        —— 考点那条 `out`+`success` 还在不在(遮过头的表现是「AI 答不出」)
    ③ 还有没有没遮到的  —— 和出事时的基准逐处比(**这一关不需要先知道有哪张新表**)
    ④ 明天会不会假红    —— 整个世界平移一天之后,基准照样对得上
    ⑤ 漏遮时真的会红吗  —— 库副本上给 DQ9001 再加一条处置轨迹,③ 必须红
"""
import io, json, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
           os.path.join(ROOT, "mcp"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏 = []


def ck(名, 取):
    """`取` 是**函数**不是值 —— 被测代码一抛异常,整个脚本当场崩掉,
    那一条 ❌ 根本没机会打印,而退出码非 0 看着像「抓到了」。"""
    try:
        ok = bool(取()); 说 = ""
    except Exception as e:
        ok, 说 = False, f"  ← **崩了**:{type(e).__name__}: {e}"
    print(f"  {'✅' if ok else '❌'} {名}{说}")
    if not ok:
        坏.append(名)


import refund_replay as RR                                  # noqa: E402
import refund_case_baseline as B                            # noqa: E402

print("三条退款研判题 · 题面材料是「出事时」的样子\n" + "=" * 76)

# ── ① 遮住了吗 ──────────────────────────────────────────────────────
import api                                                   # noqa: E402
import worldclock as W                                       # noqa: E402

c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
出事 = RR.出事于(c, "DQ9001")
生轨迹 = api.get_refund_trace("DQ9001")
生押金 = api.get_deposit("DQ9001")
c.close()

_, 遮轨迹 = RR.遮住处置痕迹(生轨迹, "DQ9001", 出事)
_, 遮押金 = RR.遮住处置痕迹(生押金, "DQ9001", 出事)
print(f"① 遮住了吗(出事于 {出事})")
ck("分界点取得到 —— 是工单创建那一刻,不是押金单建档那天", lambda: bool(出事) and " " in str(出事))
ck(f"轨迹上至少遮住一处(实际 {len(遮轨迹)} 处){'' if 遮轨迹 else ' ← 一处也没遮'}",
   lambda: len(遮轨迹) >= 1)
ck(f"押金单上至少遮住一处(实际 {len(遮押金)} 处)", lambda: len(遮押金) >= 1)
ck("押金单状态还原成出事时那个,而且**不是我在这儿写的那个字符串**",
   lambda: RR.遮住处置痕迹(生押金, "DQ9001", 出事)[0]["status"] == RR.出事时押金状态)
ck("造数脚本的状态和回测口径**同一份**(两份会漂,漂了不报错)",
   lambda: __import__("seed_triage_tasks")._RR.出事时押金状态 is RR.出事时押金状态)

# ⚠️ 工单行是「按时刻判」的盲区:`status` 和 `summary` **都没有自己的时刻**
_工单行 = B.怎么取["list_tasks"]("DQ9001")
_遮工单, _遮了工单 = RR.遮住处置痕迹(_工单行, "DQ9001", 出事)
ck(f"工单行也遮了(实际 {len(_遮了工单)} 处)—— 它的痕迹不带时刻,"
   f"「按时刻判」认不出来,所以这一行是**按名字**遮的", lambda: len(_遮了工单) >= 1)
ck("`summary` 抹成 None —— 出事时它真的是 NULL(闭环往里写的是 **AI 自己那段错判原文**)",
   lambda: _遮工单[0]["summary"] is None)
ck("工单状态还原成出事时那个", lambda: _遮工单[0]["status"] == RR.出事时工单状态)

# ── ② 遮过头了吗 ────────────────────────────────────────────────────
活 = B.视图()["单"]
print("\n② 遮过头了吗 —— 考点必须留着")
考点 = [x for x in 活["DQ9001"]["get_payment_flow"]
        if x.get("direction") == "out" and x.get("status") == "success"]
ck(f"DQ9001 遮后仍有 out+success 那条流水(它出事时就在,**正是考点**)—— 实际 {len(考点)} 条",
   lambda: len(考点) == 1)
ck("三次 TIMEOUT 一条都没被遮掉(遮掉了这道题就没题面了)",
   lambda: [x["resp_code"] for x in 活["DQ9001"]["get_refund_trace"]] == ["TIMEOUT"] * 3)
ck("DQ9002 的 ACCOUNT_CLOSED 还在", lambda: all(
    x["resp_code"] == "ACCOUNT_CLOSED" for x in 活["DQ9002"]["get_refund_trace"]))
ck("DQ9003 的 INSUFFICIENT_BALANCE 还在", lambda: all(
    x["resp_code"] == "INSUFFICIENT_BALANCE" for x in 活["DQ9003"]["get_refund_trace"]))
ck("DQ9002/9003 **没有** out 流水(有的话它们也成了「其实已退」,三条题变成同一条)",
   lambda: not [x for s in ("DQ9002", "DQ9003")
                for x in 活[s]["get_payment_flow"] if x.get("direction") == "out"])

# ── ③ 还有没有没遮到的 ───────────────────────────────────────────────
print("\n③ 和出事时的基准逐处比")
基 = B.读基准()
ck("基准文件在", lambda: 基 is not None)
差 = B.比(活, (基 or {}).get("单") or {}) if 基 else ["没有基准"]
for x in 差[:8]:
    print(f"     {R}·{D} {x}")
ck(f"逐处对得上(对不上 {len(差)} 处)", lambda: not 差)
漏盯, 没扫到 = B.没盯着的()
挂的 = B.研判挂的工具()
ck(f"研判那一轮挂的工具里,**能带出这笔单痕迹的都在基准的视野里**(挂了 {len(挂的)} 个)"
   + (f";{R}没盯着:{漏盯}{D}" if 漏盯 else ""), lambda: not 漏盯)
ck(f"而且真的扫到了源码(扫不到的:{没扫到 or '无'})", lambda: not 没扫到)
ck(f"豁免的那几条理由**还成立**({list(B.不用盯的)})", lambda: not B.过期的豁免())
_app = io.open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
ck(f"研判真跑用的还是「{B.研判角色}」这个角色 —— {B.研判真跑在[0]} 里那一行。"
   f"换了角色,这份基准盯的就是**另一个人挂的工具**"
   f"(第一版就盯错过:盯的是财务,而研判是后台运营,偏偏后者挂着 list_tasks)",
   lambda: B.研判真跑在[1] in _app)

# 最直接的一条:**那段错判原文一个字都不许出现在题面材料里**
import sqlite3 as _s3
_c2 = _s3.connect(f"file:{api.DB}?mode=ro", uri=True)
_错原文 = (_c2.execute("SELECT summary FROM task WHERE ref_id='DQ9001' AND type=?",
                       (RR.工单类型,)).fetchone() or [None])[0]
_c2.close()
_材料串 = json.dumps(活, ensure_ascii=False)
ck(f"库里那段 AI 错判原文{'(现在是 ' + repr((_错原文 or '')[:18]) + '…)' if _错原文 else '(现在是空的)'}"
   f"**一个片段都没出现在遮后的材料里** —— 这道题考的就是别得出那个结论,"
   f"而它正摆在工单行上",
   lambda: (not _错原文) or all(_错原文[i:i + 12] not in _材料串
                                for i in range(0, max(1, len(_错原文) - 12), 6)))
if not _错原文:
    print(f"     {Y}⚠️ 这一条现在是**空判**:库里那段原文是空的(这笔单还没被研判过,"
          f"或者 summary 被清过)。它绿不等于遮住了 —— 等再走一次闭环才真的量得到{D}")

# ── ③·续 题面自己干不干净 ────────────────────────────────────────────
# 遮蔽管的是**工具返回**,而题面是另一条路:它由 `ops.研判提示词()` 拼,
# 一个字都不过遮蔽。「把工单摘要加进题面当上下文」是个很自然的改动,
# 而它会让这道题直接送分 —— 摘要里就是上一轮那个错结论。
print("\n③·续 题面(ops.研判提示词)自己带没带闭环痕迹")
import ops as _ops
_bp, _case, _题面 = _ops.研判提示词(RR.工单类型, "DQ9001", "TDQ9001")
ck(f"题面里没有那段 AI 错判原文(断点 {_bp} · case {_case})",
   lambda: (not _错原文) or all(_错原文[i:i + 12] not in _题面
                                for i in range(0, max(1, len(_错原文) - 12), 6)))
ck("题面说的是**出事时**那件事(「已连续失败」),没写成闭环之后的「已退」",
   lambda: "已退" not in _题面)
ck("题面和遮后的押金单状态**对得上** —— 题面说失败而材料写着已退的话,"
   "模型会先信材料(它看得见证据),这道题就塌了",
   lambda: 活["DQ9001"]["get_deposit"]["status"] == RR.出事时押金状态)

# ── ④ 明天会不会假红 ────────────────────────────────────────────────
print("\n④ 世界平移一天之后,基准还对得上吗(假红会让这条判据被关掉)")
import datetime as _dt
生 = {s: {k: v for k, v in 活[s].items()} for s in 活}          # 活的已经归一化过


def 挪一天(x):
    """把材料里每个日期往后挪一天 —— **模拟整个世界平移**。"""
    if isinstance(x, dict):
        return {k: 挪一天(v) for k, v in x.items()}
    if isinstance(x, list):
        return [挪一天(v) for v in x]
    if RR.是时刻吗(x):
        s = x.strip()
        d = _dt.date.fromisoformat(s[:10]) + _dt.timedelta(days=1)
        return f"{d}{s[10:]}"
    return x


原料 = {s: {k: 取(s) for k, 取 in B.怎么取.items()} for s in 活}
今 = W.今天()


def 平移后的视图():
    出 = {}
    for s in 原料:
        遮 = {}
        for k, v in 原料[s].items():
            挪 = 挪一天(json.loads(json.dumps(v, ensure_ascii=False)))
            出事挪 = f"{_dt.date.fromisoformat(str(出事)[:10]) + _dt.timedelta(days=1)}{str(出事)[10:]}"
            遮[k], _ = RR.遮住处置痕迹(挪, s, 出事挪)
        遮["出事于"] = f"{_dt.date.fromisoformat(str(出事)[:10]) + _dt.timedelta(days=1)}{str(出事)[10:]}"
        出[s] = RR.归一化(遮, str(_dt.date.fromisoformat(str(今)[:10]) + _dt.timedelta(days=1)))
    return 出


ck("整库挪一天 + 世界今天也挪一天 → 归一化之后和基准**一字不差**("
   "基准里存绝对日期的话,这里会整份对不上,而那是假红)",
   lambda: not B.比(平移后的视图(), 基["单"]))
不挪的 = __import__("shift_world").整列日期不挪
要挪的列 = ["deposit.created", "deposit.updated", "refund_trace.ts",
            "payment_flow.ts", "task.created"]
ck(f"基准依赖的那几列都**不在**平移的「不挪」名单里 —— 名单里有的话,"
   f"世界挪了它不挪,第二天这条判据是真红但原因在别处;"
   + (f"{R}有:{[x for x in 要挪的列 if x in 不挪的]}{D}"
      if [x for x in 要挪的列 if x in 不挪的] else ""),
   lambda: not [x for x in 要挪的列 if x in 不挪的])

# ── ⑤ 漏遮时真的会红吗(咬合,库副本)─────────────────────────────────
print("\n⑤ 咬合:库副本上给 DQ9001 再走一步(多一条处置轨迹)—— ③ 必须红")
副本 = os.path.join(tempfile.mkdtemp(prefix="refundcase-"), "lanxiu.db")
shutil.copy2(api.DB, 副本)
cc = sqlite3.connect(副本)
cc.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key)"
           " VALUES('DQ9001',9,?,'渠道核实','1200','SUCCESS','咬合:闭环又写了一条','IDEM-DQ9001-咬合')",
           (f"{str(出事)[:10]} 23:30",))
cc.commit(); cc.close()
原DB = api.DB
try:
    api.DB = 副本
    副本差 = B.比(B.视图(副本)["单"], 基["单"])
finally:
    api.DB = 原DB
    shutil.rmtree(os.path.dirname(副本), ignore_errors=True)
ck("副本上多写一条**晚于出事**的轨迹 → 它被遮掉,基准仍然对得上("
   "按时刻判,所以**不认识的新记录也遮得住**)", lambda: not 副本差)

副本2 = os.path.join(tempfile.mkdtemp(prefix="refundcase2-"), "lanxiu.db")
shutil.copy2(api.DB, 副本2)
cc = sqlite3.connect(副本2)
# 这一条**没有时刻**可以露馅 —— 遮蔽认不出它,③ 必须靠「和基准对不上」抓到
cc.execute("INSERT INTO payment_flow(id,deposit_id,direction,amount,channel,channel_serial,status,ts)"
           " VALUES('PFDQ9001X','DQ9001','out',1200.0,'人工补退','WX咬合','success',?)",
           (f"{str(出事)[:10]} 12:00",))
cc.commit(); cc.close()
try:
    api.DB = 副本2
    副本2差 = B.比(B.视图(副本2)["单"], 基["单"])
finally:
    api.DB = 原DB
    shutil.rmtree(os.path.dirname(副本2), ignore_errors=True)
ck(f"副本上塞一条**早于出事、遮蔽认不出**的流水 → 基准必须红(实际 {len(副本2差)} 处)"
   f" —— 这一关才是「漏遮」真正的样子:遮蔽不报错,基准报", lambda: len(副本2差) >= 1)

# ── ⑥ 遮蔽到得了服务进程吗(这条链路断了,分数会更好看)──────────────────
#
# 前五关验的都是「**在这个进程里**遮得对不对」。但真跑时遮蔽跑在 **MCP 服务进程**里,
# 而那个进程是 claude CLI 拉起的 —— 父进程的 `os.environ` 到不到那一跳**没有证据**。
# 于是 `agentsite/sdk.mcp_config` 必须**显式**把单号拼进那个服务的 `env`
# (差评那条走的就是这个办法),而 `sdk.run` 必须**把参数转下去**。
#
# 🔺 这四件事里断掉任何一件,后果都不是报错,而是:
# > 材料里还写着闭环之后的「已退」—— **三道题全送分,分数更好看,没人会去查。**
#
# 判的是源码结构(ast),不是跑一次看看 —— 因为「跑一次没报错」恰恰是断掉时的样子。
# ⚠️ 这一关自己也栽过一次:只认 `ast.FunctionDef` 的写法**找不到 `async def run`**,
# 而它找不到的时候一个字都不报、`ck` 照样绿 —— 所以下面两种都要认。
print("\n⑥ 遮蔽到得了服务进程吗:env 是显式拼进去的,这条链路不许断")
import ast                                                   # noqa: E402

押金env = "LANXIU_JUDGING_DEPOSIT"


def 链路(源码):
    """(mcp_config 收不收, run 收不收, run 转不转发, mcp_config 拼不拼 env)。

    **纯函数,只吃源码文本** —— 所以下面能拿几份「改坏的样本」当场证明它真的会红,
    不用去改真文件(改真文件验红,是在门禁上验门禁)。
    """
    t = ast.parse(源码)
    收 = {"mcp_config": False, "run": False}
    转发 = 拼env = False
    for n in ast.walk(t):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue                      # ⚠️ 两种都要认:run 是 async def
        if n.name not in 收:
            continue
        收[n.name] = "被判押金" in ([a.arg for a in n.args.args] +
                                 [a.arg for a in n.args.kwonlyargs])
        if n.name == "run":
            转发 = any(isinstance(c, ast.Call)
                     and getattr(c.func, "id", None) == "mcp_config"
                     and any(k.arg == "被判押金" for k in c.keywords)
                     for c in ast.walk(n))
        else:
            拼env = 押金env in ast.dump(n)
    return 收["mcp_config"], 收["run"], 转发, 拼env


_sdk源 = io.open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
_收c, _收r, _转, _env = 链路(_sdk源)
ck(f"`mcp_config` 收 `被判押金`", lambda: _收c)
ck(f"`run` 也收(它是 `async def` —— 只认 FunctionDef 的判据在这儿会悄悄全绿)",
   lambda: _收r)
ck("`run` **把它转给了** `mcp_config`(光改 mcp_config 没用:不转发 = 永远 None)",
   lambda: _转)
ck(f"`mcp_config` 把单号**显式拼进服务的 env**(不靠环境继承 —— 那一跳没有证据)",
   lambda: _env)

# 人造对照:四份改坏的样本,每一份都必须被上面那个函数抓到。
# (「新加的判据会不会红」和「它永远绿」,在一次通过的门禁上长得一模一样。)
_好 = ("def mcp_config(me=None, 被判押金=None):\n"
       f"    env = {{}}\n    if 被判押金:\n        env = {{**env, {押金env!r}: str(被判押金)}}\n"
       "    return env\n"
       "async def run(kind, prompt, 被判押金=None):\n"
       "    return mcp_config(me=1, 被判押金=被判押金)\n")
_坏样本 = {
    "mcp_config 签名里没有它": _好.replace("def mcp_config(me=None, 被判押金=None):",
                                      "def mcp_config(me=None):"),
    "run 签名里没有它": _好.replace("async def run(kind, prompt, 被判押金=None):",
                                "async def run(kind, prompt):"),
    "run 收了却不转发": _好.replace("mcp_config(me=1, 被判押金=被判押金)", "mcp_config(me=1)"),
    "env 没拼进去": _好.replace(f"env = {{**env, {押金env!r}: str(被判押金)}}", "pass"),
}
ck("人造对照:完好的样本四项全真", lambda: all(链路(_好)))
for _名, _src in _坏样本.items():
    ck(f"人造对照 · 「{_名}」必须被抓到",
       lambda _s=_src: not all(链路(_s)))

_proto源 = io.open(os.path.join(ROOT, "mcp", "protocol.py"), encoding="utf-8").read()
ck("`遮被判那笔押金` 会往台账记一行(遮蔽在服务进程里开没开口,**只能靠它自己写下来**;"
   "评测那头的规矩是台账没这一轮的行就不记分)",
   lambda: "_记台账(单, 出事" in _proto源 and "def _记台账(" in _proto源)
import refund_sets as _RS                                    # noqa: E402
ck(f"台账那个环境变量名,评测和工具层是**同一个**(`{_RS.台账env}`)"
   f" —— 两边各写一份的话,评测会永远读到一本空台账",
   lambda: _RS.台账env in _proto源)

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。规格在 `tools/bite_specs.json` 里可重放。
#
# 挑的是 `sdk.run` 那一句转发:它是这条链路上**最像「已经做完了」的一环** ——
# `mcp_config` 的签名改了、env 也拼了,看起来齐活,而 `run` 不把参数传下去的话
# 那个形参永远是 None,遮蔽一次都不会发生。
# 而它断掉的表现不是报错,是**三道题全送分、分数更好看**。
咬合 = [
    ('把 `sdk.run` 调 `mcp_config` 时转发被判押金那个实参去掉'
     '(签名还在、env 还拼着,看起来齐活)',
     '`run` **把它转给了** `mcp_config`'),
]

print()
if 坏:
    print(f"{R}❌ {len(坏)} 处不对{D}")
    for x in 坏:
        print(f"   · {x}")
    raise SystemExit(1)
print(f"{G}✅ 题面材料是出事时的样子;漏遮会红,平移不会假红{D}")
