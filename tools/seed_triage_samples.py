#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造研判队列的样本 —— **真调模型,模型真用工具**。

    python3 tools/seed_triage_samples.py          # 只看会跑哪些,不调模型
    python3 tools/seed_triage_samples.py --做     # 真跑
    python3 tools/seed_triage_samples.py --做 --n 3   # 只跑前 3 条(验链路)

## 为什么要有这一步

`triage` 表是空的(2026-10-11 实测 0 条),而研判队列的验收门槛第一条是
「样本量 0 不叫通过」—— 基础质量看板的分母、版本对比视图、隔离试运行
三样都建立在这张表上。用户 2026-10-10 的原话:「都不砍,我都要,缺稳定数据,可以造」。

**不手造。** 四段(根因/建议动作/证据/置信度)和置信度都是 `ops` 从
**过程信号**推出来的:查了几次数据、证据齐不齐。直接 INSERT 一条
「置信度=高」的记录,等于把看板的分子分母一起编掉。
> 一条真跑出来的研判,和一条手填的,**在 triage 表上长得一模一样** ——
> 四段齐、置信度也有,只有「模型到底查过没查过」这一点泄露了它。

## 口径只有一份

提示词和断点号从 `backend/ops.研判提示词` 取,**这里不抄**。
它原来长在 `agentsite/app.py` 的 HTTP 处理函数里,2026-10-11 抽出来的 ——
两份提示词的后果不是「不一致」,是**样本在替另一句话打分**。

## 三类能跑,第四类不跑(而且不是跳过,是说清)

    BP-01 财务人工任务   24 条
    BP-02 客户合并确认   16 条
    BP-03 售后判责       12 条
    ——   评价差评      214 条  ← **不跑**

差评占队列八成,而方案**自己声明**「差评的 AI 辅助默认关闭 —— 等专用取数和
独立评测接通后再启用」,业务 2026-10-10 也拍了「评价差评 → 店长确认」。
所以差评不该有 AI 研判记录。**也不替它造「人工研判」记录** ——
那是在假装 AI 跑过(`resolve` 要先有一条 triage 才能销账)。
它该以「不进质量看板分母」的身份被显示出来,不是被填上。

⚠️ 原来 `agentsite` 那边是 `断点.get(类型, "BP-02")`,差评掉进客户合并分支去
`ref.split("|")` 当场崩 —— 立项文档里「差评错进客户合并分支」就是它。已改成显式拒绝。

## 不造「已改判」—— 这条是安全判断,不是偏好

`ops.resolve()` 判「已改判」时**把人的裁决写进 `truth` 表**,而 `truth` 是评测答案。
`ops.resolve` 自己的注释写明了为什么要分开标 src:
> 回流条目只经过一个人的判断、没有第二个人复核过,如果和建库标注混在一起,
> **一次判错的裁决会悄悄变成"标准答案",而且再也查不出来**。

脚本造的「改判」连一个人的判断都没有。**造它等于往评测答案里灌编的东西**,
而评测集一旦污染就再也不能当评测集。所以这里只造 `待复核` / `已采纳` / `已升级`,
「已改判」留给真人。要样本的话,得由值班同学在页面上真裁决一次。

## 调不动模型的时候

用户 2026-10-11 拍的是「**配方里每次真调模型**」(不走录制回放)。
代价要说清:**CI 上调不动模型,所以 CI 的库里这张表会是空的**,
依赖它的判据在 CI 上一个字都没验。

**凭据是探出来的,不是猜出来的**:先真跑一条,挂了再判 ——
放行的两个判据,**第二个才是靠得住的那个**:
  ① 错误话里有认证字样 —— 够用,但它是**在猜报错字符串**,换个 SDK 版本、
     换个失败方式(超时 / CLI 没装 / 配额)就不匹配。
  ② `CI=true`(GitHub Actions 永远设它)—— 这是一句**关于环境能力的事实陈述**:
     CI 上没有模型凭据,所以「调不动模型」在那里不算构建失败;在本机算,
     本机就该有凭据,调不动是真出事了。
只留 ① 的话,CI 会因为「报错话术和我猜的不一样」而红,
**而红的理由和任何人做的事都无关**。
放行时**大声打印**(静默的话「跳过了」和「跑过了」在输出上长得一模一样)。
(第一版写的是 `if not os.environ.get("ANTHROPIC_API_KEY")` —— 而 Claude 这一路
**主动 pop 掉**那个变量、用 CLI 的登录态,所以那个判断会在能跑的机器上也跳过。)
"""
import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "agentsite")]

import ops as OPS          # noqa: E402  提示词/断点/落库/销账,全在这一份


def _要sdk():
    """拿到 `sdk`,**必要时换解释器重入自己**。

    ⚠️ `claude_agent_sdk` 只装在 `agentsite/.venv` 里,而 `tools/rebuild.sh` 统一用
    `python3 $STEP` 跑每一步。两条路只能有一条让步 —— 让这一步自己换解释器,
    而不是给配方开一个特例:配方里一旦有「这一步要用另一个 python」的例外,
    下一个加步骤的人不会知道,而**漏掉例外和加对了步骤在输出上长得一模一样**。

    `import sdk` 放在函数里(不在模块顶上):只看不做、以及没凭据时都不需要它,
    顶上 import 会让这两条路也被 venv 绑住。
    """
    try:
        import sdk                                    # noqa: PLC0415
        return sdk
    except ModuleNotFoundError:
        pass
    venv路径 = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
    if os.environ.get("LANXIU_TRIAGE_REEXEC") or not os.path.exists(venv路径):
        raise SystemExit(
            f"{R}❌{D} 没有 agentsite/.venv —— `claude_agent_sdk` 只装在那里面。\n"
            f"   先 ./start.sh 建一次,或直接用 ./agentsite/.venv/bin/python 跑本脚本。")
    os.environ["LANXIU_TRIAGE_REEXEC"] = "1"
    print(f"{Y}↻{D} 换 agentsite/.venv 的解释器重入(claude_agent_sdk 只装在那儿)")
    os.execv(venv路径, [venv路径, os.path.abspath(__file__)] + sys.argv[1:])

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# 销账样本的配比。**按序号定,不随机** —— 重跑要拿到同一批。
# 「已改判」不在里面,理由见模块头。
销账配比 = {3: ("已采纳", "张静静", "店长"), 7: ("已升级", "魏欣新", "总部运营")}


def 能跑的工单(说=print):
    """队列里**有 AI 研判分支**的那些。差评不在内 —— 它不是漏了,是不该跑。"""
    行 = OPS.queue()
    可跑, 不跑 = [], {}
    for r in 行:
        try:
            bp, case, prompt = OPS.研判提示词(r["type"], r["ref"], r["task_id"])
        except ValueError:
            不跑[r["type"]] = 不跑.get(r["type"], 0) + 1
            continue
        可跑.append(dict(task_id=r["task_id"], type=r["type"], bp=bp,
                        case=case, prompt=prompt, state=r.get("状态") or r.get("state")))
    说(f"队列 {len(行)} 条 · 能跑 {len(可跑)} 条 · 不跑 {不跑}")
    说(f"  ← 不跑的不是漏了:差评的 AI 辅助**默认关闭**(方案自己声明),"
       f"由店长人工确认(业务 2026-10-10 拍)")
    return 可跑


def 拦已裁决的(可跑, 说=print):
    """已经有人裁决过的,**不许覆盖**。

    幂等本该是「先删自己那批再重做」,但这张表上做不到:`triage` 没有
    「谁造的」这一列,而**人在页面上裁决过的记录和脚本造的长得一模一样**。
    而「已改判」那一种裁决已经回流进 `truth`(评测答案)—— 删掉它等于
    悄悄改评测集。所以这里不赌:见到已裁决的就停,让人来处理。
    """
    脏 = []
    for x in 可跑:
        for t in OPS._rows("SELECT id,status FROM triage WHERE task_id=?", x["task_id"]):
            if t["status"] != "待复核":
                脏.append((x["task_id"], t["id"], t["status"]))
    if 脏:
        说(f"{R}❌{D} 有 {len(脏)} 条研判已经被人裁决过,**不覆盖**:{脏[:5]}")
        说("   「已改判」那种裁决已经回流进 truth(评测答案)—— 删它等于悄悄改评测集。")
        说("   要重造请先人工处理这几条。")
    return 脏


def 跑一条(x, 说=print):
    """真调模型 → 落库。返回 triage 行。"""
    t0 = time.time()
    r = asyncio.run(_要sdk().run("task", x["prompt"]))
    ms = int((time.time() - t0) * 1000)
    tid = OPS.save_triage(
        x["task_id"], x["bp"], x["case"], r["text"], r["trajectory"],
        cost=r.get("cost_usd"), latency_ms=ms, model=r.get("model"),
        usage=r.get("usage"), guard_blocked=r.get("guard_blocked"),
        guard_violations=r.get("guard_violations"),
        answer_turns=r.get("answer_turns"), trace_id=r.get("trace_id"))
    行 = OPS.get_triage(tid)
    说(f"  {x['bp']} {x['task_id']}  置信度 {行.get('ai_confidence')} · "
       f"工具 {行.get('tool_calls')} 次 · {ms} ms")
    return 行


def 复查(说=print):
    """**「写进去了」和「写对了」是两件事。**"""
    坏 = 0

    def ck(名, 行了, 说明=""):
        nonlocal 坏
        说(f"  {'✅' if 行了 else '❌'} {名}" + (f"  {说明}" if 说明 else ""))
        坏 += (not 行了)

    n = OPS._rows("SELECT count(*) c FROM triage")[0]["c"]
    ck(f"样本量:{n} 条", n > 0,
       "← **样本量 0 的时候下面每一项都成立** —— 一张空表没有任何不一致")
    if not n:
        return 坏
    四段齐 = OPS._rows(
        "SELECT count(*) c FROM triage WHERE ai_root_cause IS NOT NULL AND ai_root_cause<>''"
        " AND ai_action IS NOT NULL AND ai_action<>''"
        " AND ai_evidence IS NOT NULL AND ai_evidence<>''")[0]["c"]
    说(f"  四段齐全的:{四段齐}/{n}")
    用过工具 = OPS._rows("SELECT count(*) c FROM triage WHERE tool_calls>=2")[0]["c"]
    ck(f"真用了工具(≥2 次)的:{用过工具}/{n}", 用过工具 > 0,
       "← 置信度是从**过程信号**推的:一次工具都没调的研判,"
       "和一条编出来的在那一列上长得一模一样")
    空草稿 = OPS._rows("SELECT count(*) c FROM triage WHERE ai_text IS NULL OR ai_text=''")[0]["c"]
    ck(f"草稿正文空着的:{空草稿}", 空草稿 == 0, "← 空正文说明没真跑,是手填的")
    断点 = {r["breakpoint"]: r["c"] for r in
            OPS._rows("SELECT breakpoint, count(*) c FROM triage GROUP BY 1")}
    ck(f"三个断点都有样本:{断点}", len(断点) >= 3,
       "← 只有一个断点有样本的话,版本对比视图没得比")
    差评 = OPS._rows("SELECT count(*) c FROM triage t JOIN task k ON k.id=t.task_id "
                    "WHERE k.type='评价差评'")[0]["c"]
    ck(f"差评一条研判记录都没有:{差评}", 差评 == 0,
       "← 差评的 AI 辅助默认关闭;有记录说明它又掉进别的分支了")
    return 坏


def main():
    ap = argparse.ArgumentParser(description="造研判队列样本(真调模型)")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--n", type=int, default=0, help="只跑前 N 条(0=全跑)")
    a = ap.parse_args()

    可跑 = 能跑的工单()
    if not 可跑:
        print(f"{R}❌{D} 一条能跑的都没有 —— **这不叫「队列是空的」,叫取数取空了**")
        return 1
    if a.n:
        可跑 = 可跑[:a.n]
    分类 = {}
    for x in 可跑:
        分类[x["bp"]] = 分类.get(x["bp"], 0) + 1
    print(f"会跑 {len(可跑)} 条:{分类}")

    if not a.做:
        print(f"{Y}只看不做{D}(不调模型)。真跑加 --做")
        return 0

    # ⚠️ **凭据是探出来的,不是猜出来的。**
    #
    # 第一版这里写的是 `if not os.environ.get("ANTHROPIC_API_KEY"): 跳过` ——
    # 而 Claude 这一路**根本不用那个变量**:`sdk._env()` 对 claude provider
    # 是**主动 pop 掉** `ANTHROPIC_API_KEY`,让 CLI 用它自己的登录态
    # (登录态在 keychain 里,不是文件)。所以那个判断会在**本来能跑的机器上也跳过**,
    # 而跳过的时候 triage 表是空的、别的检查照样绿。
    # > 一台「没有凭据」的机器,和一台「凭据不在那个环境变量里」的,
    # > **在 `os.environ.get` 上长得一模一样。**
    #
    # 改成:**先真跑一条**,挂了再按错误分类。认证问题 → 大声说清然后放行
    # (没有凭据不是配方的毛病,不该把 CI 判红);别的问题 → 当场失败。
    认证词 = ("unauthorized", "authentication", "credential", "api key", "api_key",
            "not logged in", "401", "403", "login")
    # ⚠️ **先把解释器换好再动库。** 换解释器是 execv —— 它会把这个进程整个替换掉,
    # 跑到第一条才换的话,前面删过的旧记录就在一个「已经不存在的进程」里发生过了。
    _要sdk()
    if 拦已裁决的(可跑):
        return 1
    删 = OPS._rows("SELECT count(*) c FROM triage")[0]["c"]
    if 删:
        with OPS._c() as c:
            c.execute("DELETE FROM triage WHERE status='待复核'")
        print(f"  删掉旧的待复核研判 {删} 条(幂等:先删自己那批再重做)")

    好, 挂 = [], []
    for i, x in enumerate(可跑):
        try:
            好.append(跑一条(x))
        except Exception as e:
            话 = f"{type(e).__name__}: {e}"
            # 第一条就挂 —— 这台机器调不动模型,不是数据的问题。
            #
            # 两个判据,**第二个才是靠得住的那个**:
            #   ① 错误话里有认证字样 —— 够用,但它是**在猜报错字符串**,
            #      换个 SDK 版本、换个失败方式(超时 / CLI 没装 / 配额)就不匹配了。
            #   ② `CI=true` —— GitHub Actions 永远设它。这是一句**关于环境能力的
            #      事实陈述**:CI 上没有模型凭据,所以「调不动模型」在那里不算构建失败;
            #      在本机算 —— 本机就该有凭据,调不动是真出事了。
            #
            # 只留 ① 的话,CI 会因为「报错话术和我猜的不一样」而红,
            # **而红的理由和任何人做的事都无关**。
            if not 好 and (any(w in 话.lower() for w in 认证词)
                           or os.environ.get("CI")):
                print(f"{Y}⚠️  调不动模型(认证),这一步没造任何样本。{D}")
                print(f"   {话[:200]}")
                print("   用户 2026-10-11 拍的是「配方里每次真调模型」,代价就是这个:")
                print(f"   {Y}**这个库里 triage 表是空的,依赖它的判据在这一轮一个字都没验**{D} ——")
                print("   而别的检查照样会绿。要有样本就得在登录过的机器上跑这一步。")
                print(f"   (判据:{'错误话里有认证字样' if any(w in 话.lower() for w in 认证词) else 'CI=true —— 这个环境本来就没有模型凭据'};"
                      f"不把这一轮判成失败:没有凭据不是配方的毛病。)")
                return 0
            挂.append((x["task_id"], 话[:120]))
            print(f"  {R}✗{D} {x['task_id']}  {话}"[:140])
            # 用户拍的是「跑满 52 条」,但连挂三条还一条没成 = 链路坏了,
            # 不是这几条数据特殊。**接着跑只会把同一个错重复 49 遍。**
            if len(挂) >= 3 and not 好:
                print(f"{R}❌{D} 前 3 条全挂、一条没成 —— **链路坏了,不是数据特殊**,停。")
                print(f"   挂的理由:{[y[1] for y in 挂]}")
                return 1
    print(f"跑完:成 {len(好)} 条 · 挂 {len(挂)} 条")
    if 挂:
        print(f"  {Y}挂掉的:{挂[:5]}{D}")

    # 销账样本:只造 已采纳 / 已升级。**不造已改判** —— 理由见模块头。
    销 = 0
    for i, 行 in enumerate(好):
        决 = 销账配比.get(i % 10)
        if not 决:
            continue
        decision, who, role = 决
        try:
            OPS.resolve(行["id"], decision, who,
                        note=f"造样本({role}):这一条只为让队列的「{decision}」状态有样本。"
                             f"**不造「已改判」** —— 那会回流进 truth(评测答案)。")
            销 += 1
        except Exception as e:
            print(f"  {R}✗{D} 销账 triage#{行['id']} 失败:{type(e).__name__}: {e}"[:120])
    print(f"  销账样本 {销} 条(已采纳 / 已升级;已改判留给真人)")

    坏 = 复查()
    if 坏 or 挂:
        print(f"{R}❌ 复查 {坏} 处不对 · 跑挂 {len(挂)} 条{D}")
        return 1
    print(f"{G}✅ 研判样本造好了{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
