#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三条**退款异常**研判题 —— 题目标识、真值、判分器。用户 2026-10-15 拍「加进研判评测题」。

    python3 agent/refund_sets.py              # 看三道题和真值(不调模型)
    python3 agent/refund_sets.py --冻         # 冻结题目标识 + 真值 + 分界点
    .venv/bin/python agent/refund_sets.py --做 --轮 2    # 真跑,连跑两轮(要 agentsite 的 venv)

## 为什么**不**混进差评那三套题

差评那三套(`agent/triage_sets.py`)按时间切,真值取 `rating.handle_way`,
而那一列**是脚本随机填的**(`rng.random() < 0.22`)—— 那套题自己的注释写得很清楚:
「判据在工作、尺子是准的、而被量的那个东西是假的」。

这三条的真值是**放进去的事实**:`tools/seed_triage_tasks.退款真因` 里那三种退款失败,
每一种的 `resp_code` 不同。两种真值的**强度不是一个量级**,混在一套里会把强度拉平 ——
一份「12 道题 9 道真值可靠、3 道随机」的成绩单,和一份「全部可靠」的,在总分上长得一模一样。

所以**另立一节**(`agent/refund-sets.json`),差评那三套**一个字没动**。
⚠️ 「分数不可比」要说准:差评三套的分**仍然可比**;不可比的是「研判评测」这个**总分** ——
题数变了,而且新三条的真值强度和老的不是一种。分界点见冻结文件里的 `分界点`。

## 真值和判据的「针」**全部从库里现取**,不在这儿手写中文短语

这个项目在「枚举中文短语当判据」上栽过七次,所以:

· **真值**:按这笔单轨迹上的 `resp_code` 回查 `退款真因` —— 匹配的那一条就是真因。
  `resp_code` 本身就是放进去的那个事实的一部分,所以这是**认**,不是**算**。
· **判据的针**:直接用库里那几条记录的 `resp_msg` / `channel_serial` / `direction` ——
  题面里有什么,判据就查什么。手写一份「正确答案可能怎么说」的短语表,
  下一个改了措辞的好答案就会被判错,**而判错的方向是「模型变差了」**。
· **结构**用 `agent/textmatch.py`:`in_sentence` 查「这个限定词是在说谁」,
  `find` 查「这个说法有没有被否定」 —— 中文里拒绝一件事几乎总要先把那件事说出来,
  只查「提到没提到」必然误判。

唯一一处手写的词是**动作名**(重发那一族),而主词 `重新发起` 取自
`backend/refund_write` 真有的那个写口,别名在那条判据里逐个写明理由。

## 三条各考什么

    DQ9001 渠道超时但实际已退 → 考**查不查支付流水**。三次 TIMEOUT 在退款轨迹里,
           而「钱已经出去了」的证据只在那条 out+success 上。只看轨迹必判「渠道故障」,
           而按渠道故障处理就会**重发,钱出去两次**。
    DQ9002 原支付渠道已注销   → 考认不认 ACCOUNT_CLOSED、**别建议重试**(重试一定再失败)。
    DQ9003 商户账户余额不足   → 考会不会把**商户侧**的问题说成**客户侧**的。

## 题面材料不冻在这儿

材料真跑时**现取 + 遮蔽**(用户 2026-10-16 在两条路里选的),
遮法在 `knowledge/refund_replay`,而「遮全了没有」由 `agent/refund_case_check.py`
拿**出事时的基准**逐处比着答。⚠️ `DQ9001` 已经被走完闭环,
不遮的话材料里直接写着「已退」—— 那道题谁都答得对。
"""
import argparse, io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
           os.path.join(ROOT, "tools"), os.path.join(ROOT, "mcp"), os.path.join(ROOT, "agentsite")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import textmatch as tm                                        # noqa: E402
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
冻结文件 = os.path.join(HERE, "refund-sets.json")
存 = os.path.join(HERE, "refund-sets-results.jsonl")

# 研判真跑用的角色 —— 和基准那边同一个来源,见 refund_case_baseline.研判角色
import refund_case_baseline as _B                             # noqa: E402
角色 = _B.研判角色


def 真因们():
    """`退款真因` 常量 —— **从造数脚本现取**(用户要求 1:真值是放进去的事实)。"""
    import seed_triage_tasks as S
    return S.退款真因


def 题们(dbp=None):
    """库里那三笔单 → 三道题。**真值靠 resp_code 认**,不靠顺序猜。

    ⚠️ 不按「`DQ9001` 是常量里第一条」这种顺序对应:每日造数「不够 3 条就补」
    会接着往后发号,顺序一旦错位,**真值会整体挪一位**,而三道题照样跑得出来、
    照样有分数 —— 只是每一道都在用别人的真值。
    """
    import sqlite3
    import api
    c = sqlite3.connect(f"file:{dbp or api.DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    出 = []
    for 单 in _B.三条单(dbp or api.DB):
        轨 = [dict(r) for r in c.execute(
            "SELECT attempt,resp_code,resp_msg FROM refund_trace WHERE deposit_id=? ORDER BY attempt", (单,))]
        流 = [dict(r) for r in c.execute(
            "SELECT id,direction,status,channel_serial FROM payment_flow WHERE deposit_id=?", (单,))]
        工单 = c.execute("SELECT id FROM task WHERE ref_id=? AND type='财务人工任务'", (单,)).fetchone()
        码 = {x["resp_code"] for x in 轨 if x["attempt"] <= 3}
        认出 = [(因, 真迹, 已退) for 因, 真迹, 已退 in 真因们()
                if {c0 for c0, _ in 真迹} == 码]
        assert len(认出) == 1, (
            f"{单} 的返回码 {码} 在 `退款真因` 里认不出唯一一条(认出 {len(认出)} 条)—— "
            f"**真值认不出来就不许出题**:认错的那道题照样跑得出分数")
        因, 真迹, 已退 = 认出[0]
        出账 = [x for x in 流 if x["direction"] == "out" and x["status"] == "success"]
        出.append(dict(
            押金单=单, 工单=(工单[0] if 工单 else None), 真因=因, 实际已退=bool(已退),
            返回码=sorted(码), 返回说明=sorted({x["resp_msg"] for x in 轨 if x["attempt"] <= 3}),
            出账流水号=[x["channel_serial"] for x in 出账],
            考=考什么(因), 真值来路="tools/seed_triage_tasks.退款真因(常量,放进去的事实)"))
    c.close()
    return 出


def 考什么(因):
    """这道题考什么 —— 一句话,**跟着真因走**,不按单号写死。"""
    if "实际已退" in 因:
        return ("查不查支付流水:三次超时在退款轨迹里,而「钱已经出去了」的证据只在那条 "
                "out+success 上。只看轨迹必判「渠道故障」,而按渠道故障处理会**重发,钱出去两次**")
    if "注销" in 因:
        return "认不认收款账户已注销这件事,**别建议重试** —— 重试一定再失败一次"
    return "会不会把**商户侧**的问题说成**客户侧**的"


# ── 判分器 ─────────────────────────────────────────────────────────────
#
# 重发那一族动作名:主词取 `backend/refund_write` 真有的那个写口,别名逐个写明理由。
# ⚠️ 这是整个判分器里**唯一**手写的词表,所以它要尽量短、而且判定靠的是**否定结构**
# (出现了但被否定 = 它在说「不要重发」),不是「出现了就算」。
def 重发那一族():
    import refund_write as RW
    主 = "重新发起" if hasattr(RW, "重新发起") else None
    assert 主, "backend/refund_write 里没有「重新发起」这个写口了 —— 动作名换了,判据跟着失效"
    return (主,            # 系统里真有的那个动作
            "重试",        # 模型最常用的说法(真实回答里出现过:「三次自动重试均失败」)
            "再次发起",    # 同一个动作的另一种说法
            "重新退款")    # 同上


def 判一题(题, 文, 轨迹):
    """一道题的判定。返回 dict,**每一条都说出它查的是什么**。

    `轨迹` 是调过的工具名列表 —— **轨迹先于内容**:该查的没查,后面说得再漂亮也不算。
    """
    文 = str(文 or "")
    工具 = " ".join(str(x).split("__")[-1] for x in (轨迹 or []))
    条 = []

    def 记(名, 过, 凭什么, 要紧=True):
        条.append(dict(名=名, 过=bool(过), 凭什么=凭什么, 计入过关=要紧))

    重发 = 重发那一族()
    未被否定的重发 = tm.says(文, 重发)            # 返回命中的那个词;被否定的不算
    提到过重发 = tm.mentions(文, 重发)

    if 题["实际已退"]:
        # ① 轨迹:查没查支付流水 —— 客观事实,不靠词
        记("查过支付流水", "get_payment_flow" in 工具,
           f"调过的工具:{工具 or '(一个都没调)'}")
        # ② 内容:有没有引那条**出账成功**的证据。针是库里的流水号 / 方向 / 状态,
        #    **不是我手写的「钱已经退了」那种短语**
        针 = tuple(题["出账流水号"]) + ("out",)
        命中 = tm.mentions(文, 针) or tm.in_sentence(文, "流水", ("out", "成功", "success"))
        记("说出了钱实际已退(引了那条出账流水)", bool(命中),
           f"针(全部来自库里那条流水):{针};命中:{str(命中)[:60]!r}")
        # ③ 不许建议重发 —— 「提到了但被否定」正是要的那个答案(「不要重发」)
        记("没建议重发(提到也行,只要是被否定的)", not 未被否定的重发,
           f"未被否定地出现的重发词:{未被否定的重发!r};提到过:{提到过重发!r}")
    else:
        # ① 认出返回码 / 返回说明 —— 针直接用库里那两列
        针 = tuple(题["返回码"]) + tuple(题["返回说明"])
        记("认出了渠道给回来的那个原因", bool(tm.mentions(文, 针)),
           f"针(库里的 resp_code / resp_msg):{针}")
        if "注销" in 题["真因"]:
            记("没建议重试(账户已注销,重试一定再失败)", not 未被否定的重发,
               f"未被否定地出现的重发词:{未被否定的重发!r}")
        else:
            # 商户侧 / 客户侧:**问「余额不足」这句话是在说谁」**,不问「提到没提到商户」
            句 = tm.in_sentence(文, "余额不足", ("商户",))
            错侧 = tm.in_sentence(文, "余额不足", ("客户", "顾客"))
            记("把余额不足算在**商户**侧", bool(句),
               f"「余额不足」所在那句里有「商户」:{str(句)[:60]!r}")
            记("没把它说成**客户**侧", not (错侧 and not 句),
               f"那句里出现客户 / 顾客而没有商户:{str(错侧)[:60]!r}")
    必 = [x for x in 条 if x["计入过关"]]
    return dict(押金单=题["押金单"], 真因=题["真因"], 考=题["考"],
                过=all(x["过"] for x in 必), 条条=条,
                没过的=[x["名"] for x in 必 if not x["过"]])


def 判一轮(判们):
    return dict(题数=len(判们), 过=sum(1 for x in 判们 if x["过"]),
                没过的=[dict(押金单=x["押金单"], 真因=x["真因"], 没过的=x["没过的"]) for x in 判们 if not x["过"]],
                全过=all(x["过"] for x in 判们) if 判们 else None)


def 判两轮(轮一, 轮二):
    """**连跑两轮、报两轮的数**(用户要求 5;CLAUDE.md:单轮结果下过四次错结论)。"""
    a, b = 判一轮(轮一), 判一轮(轮二)
    同 = {x["押金单"] for x in 轮一 if not x["过"]} == {x["押金单"] for x in 轮二 if not x["过"]}
    return dict(第一轮=a, 第二轮=b, 两轮都全过=bool(a["全过"] and b["全过"]),
                两轮没过的是不是同一批=同,
                一句话=("两轮都全过" if a["全过"] and b["全过"] else
                        "两轮没过的是同一批 —— 像是稳定的能力缺口" if 同 else
                        "两轮没过的**不是同一批** —— 这是抖动,单轮的数不许用来下结论"))


# ── 冻结 ───────────────────────────────────────────────────────────────
def 分界点():
    """哪个提交之后的分数和以前不可比 —— **取当前 HEAD**,不手写。"""
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()[:12]
    except Exception as e:
        return f"(取不到 git HEAD:{type(e).__name__})"


def 冻(dbp=None, 路径=冻结文件):
    题 = 题们(dbp)
    出 = dict(
        说明="三条退款异常研判题(用户 2026-10-15 拍「加进研判评测题」)。"
             "**只冻题目标识和真值**,题面材料真跑时现取 + 遮蔽 —— 库会变,"
             "而一份冻在文件里的材料会悄悄过期,过期时不报错、只会让题越来越不像真的。",
        真值来路="tools/seed_triage_tasks.退款真因;按这笔单轨迹的 resp_code 回查认出来,不按顺序猜",
        题面材料="现取 + 遮蔽(knowledge/refund_replay),"
                 "遮全了没有由 agent/refund_case_check.py 拿出事时的基准逐处比",
        分界点=dict(
            提交=分界点(),
            怎么读="这个提交**之后**的「研判评测总分」和它之前的**不可比** —— 题数变了,"
                   "而且这三条的真值是放进去的事实,比差评那三套(脚本随机填的标注)强一个量级,"
                   "混在一个总分里会把强度拉平。",
            仍然可比的="差评那三套题**一个字没动**(agent/triage-sets.json),它们各自的分照旧可比",
            此前的结果="agent/triage-pipeline-results.jsonl 等结果文件**不要覆盖**(用户要求 4)"),
        角色=f"研判真跑用「{角色}」这个角色(agentsite/app.py)",
        题=题)
    io.open(路径, "w", encoding="utf-8").write(json.dumps(出, ensure_ascii=False, indent=1) + "\n")
    return 出


def 读冻结(路径=冻结文件):
    return json.loads(io.open(路径, encoding="utf-8").read()) if os.path.exists(路径) else None


# ── 真跑(要 agentsite 的 venv)────────────────────────────────────────
def 跑一题(题):
    """跑一道:题面从 `ops.研判提示词` 现取,材料靠 env 遮蔽,**一个字都不落库**。

    ⚠️ **不许走 `app.py` 的 `/api/run-triage`** —— 那条路跑完会 POST 到
    `/api/ops-triage`,于是:把工单改成「待复核」、**把这一轮的根因写进 task.summary**。
    评测自己把题面改了,而下一轮读到的材料里就带着上一轮的答案。
    """
    import asyncio
    import ops as _ops
    import sdk
    bp, case, prompt = _ops.研判提示词("财务人工任务", 题["押金单"], 题["工单"])
    原 = os.environ.get("LANXIU_JUDGING_DEPOSIT")
    try:
        os.environ["LANXIU_JUDGING_DEPOSIT"] = 题["押金单"]     # ← 遮蔽:出事时的样子
        r = asyncio.run(sdk.run(角色, prompt))
    finally:
        if 原 is None:
            os.environ.pop("LANXIU_JUDGING_DEPOSIT", None)
        else:
            os.environ["LANXIU_JUDGING_DEPOSIT"] = 原
    return r


def 做(轮数=2):
    import datetime as _dt
    题 = 题们()
    轮们 = []
    for 轮 in range(1, 轮数 + 1):
        判们 = []
        for t in 题:
            r = 跑一题(t)
            判 = 判一题(t, r.get("text"), r.get("trajectory"))
            判.update(轮=轮, 置信度那段=None, 调了几个工具=len(r.get("trajectory") or []),
                      交付检查=((r.get("交付检查") or {}).get("状态")), 模型=r.get("model"),
                      花了=r.get("cost_usd"), 原文=r.get("text"))
            判们.append(判)
            print(f"  轮{轮} {t['押金单']} {'✅' if 判['过'] else '❌'} "
                  f"{'' if 判['过'] else 判['没过的']}")
        轮们.append(判们)
    报 = 判两轮(轮们[0], 轮们[1]) if len(轮们) >= 2 else 判一轮(轮们[0])
    with io.open(存, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(跑于=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                分界点=分界点(), 轮数=轮数, 报=报,
                                逐轮=轮们), ensure_ascii=False) + "\n")
    return 报


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--冻", action="store_true")
    ap.add_argument("--做", action="store_true")
    ap.add_argument("--轮", type=int, default=2)
    a = ap.parse_args()
    if getattr(a, "冻"):
        d = 冻()
        print(f"{G}已冻结{D} {冻结文件} —— {len(d['题'])} 道;分界点 {d['分界点']['提交']}")
    elif getattr(a, "做"):
        print(f"三条退款异常 · 真跑 {a.轮} 轮(角色 {角色};材料现取 + 遮蔽;**不落库**)")
        报 = 做(a.轮)
        print("\n" + json.dumps(报, ensure_ascii=False, indent=1))
    else:
        for t in 题们():
            print(f"· {t['押金单']}(工单 {t['工单']}) · 真因「{t['真因']}」")
            print(f"    考:{t['考']}")
            print(f"    返回码 {t['返回码']};出账流水 {t['出账流水号'] or '无'}")
