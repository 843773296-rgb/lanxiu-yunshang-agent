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
坏工具, 没扫到 = B.够得着工单表吗()
ck(f"财务角色挂的工具**没有一个**读 task / triage 表 —— "
   f"闭环把 AI 那段错判原文写进了 `task.summary`(ops.py:682),挂上就是送分口"
   + (f";{R}有:{坏工具}{D}" if 坏工具 else ""), lambda: not 坏工具)
ck(f"而且这一关真的扫到了源码(扫不到的:{没扫到 or '无'})", lambda: not 没扫到)

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


原料 = {s: {k: getattr(api, k)(s) for k in B.按押金单查的} for s in 活}
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

print()
if 坏:
    print(f"{R}❌ {len(坏)} 处不对{D}")
    for x in 坏:
        print(f"   · {x}")
    raise SystemExit(1)
print(f"{G}✅ 题面材料是出事时的样子;漏遮会红,平移不会假红{D}")
