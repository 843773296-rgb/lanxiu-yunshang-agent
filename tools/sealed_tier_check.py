#!/usr/bin/env python3
"""**封存题**守三件事:每面正好 5 道 · **一道都不许出现在结果文件里** · 每道都有对照。

封存题是什么:写了但**故意不跑**的那一批(用户 2026-11-11 拍:罕见层每面 16 道,
封存 5 道、平时跑 11 道)。它们留到最终验收 —— 因为**一道题跑过一次、分数被人看过
之后,就只能证明「在这道题上调得好」**,不再能证明能力。

这条检查为什么必须存在(两边各守一半,**只配一边就是净放宽**):

  · 那 10 道题放在 `agent/ops_sealed.py` 里,文件名不匹配 `*_eval.py`,
    所以 `eval_tier_check` 的 AST **扫不到它们**,不会要求「跑过」——
    这是**有意的隔离**,也是**一个口子**:
    > 一道「说好不跑所以没跑」的题,和一道「悄悄被跑了、分数已经被看过」的题,
    > **在源码上长得一模一样** —— 而后者意味着这一面的最终验收已经失效,
    > 且**没有任何别的检查会发现**(分层、失效闸都只从结果文件取题,
    > 它们看见封存题只会当成普通罕见题)。
    所以这里反过来守:**封存题出现在任何结果文件里 → 红。**

  · 第二半:**判据不能跟着题一起隐身。**
    > 一个「判据验过了」和一个「判据从没被任何对照碰过」,
    > **在解封那天之前长得一模一样** —— 而解封正是最不能出错的时刻。
    所以要求每道封存题在 `ops_eval_judgetest` 里至少有一条对照
    (那份对照集已经改成盖 `CASES + SEALED`)。

⚠️ **样本量**:封存题数为 0 **要红** —— 空集合上这三条性质全自动成立,
而「一道封存题都没找到」和「全都合规」在那句绿字上长得一模一样。

⚠️ 这条检查**不判断封存题难不难** —— 它们一道都没跑过,难度是未知的。
   解封时别把「判据分得开」读成「难度合适」。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), ROOT]

# ── 咬合记录(每条在 tools/bite_specs.json 里有可执行规格,**都手跑验过能红**)──
咬合 = [
    # ① 承重墙:说好不跑的题被跑了
    ("把一道封存题的题号写进 ops 的结果文件(`{\"id\": \"W01\"` → `\"G09\"`)",
     "封存题一道都没出现在结果文件里"),
    # ② 隔离失效:下一个人把封存题塞回日常题集
    ("把一道封存题的题号改成和日常题撞号(G09 → G01)",
     "封存题不在日常题集里"),
    # ③ 约定变了而题没跟上
    ("把「每面封存几道」从 5 改成 6,而题一道没补",
     "每面正好"),
    # ⚠️ **第四个攻击点试过两次,两次都过不了第三关(红的不止指定那条):**
    #    · 删掉一道封存题的对照 → 连带让标点不变量的样本量塌掉,红两条;
    #    · 把封存题号改成 Z09(新面)→ 连带让「每道都有对照」红,也是两条。
    #    换成改那个常量才只红一条。
    # ⚠️ **三态判定(不适用 / 读不了)没有咬合规格,因为它在当下数据上观察不到**:
    #    按套隔离之后只扫 2 份 ops 自己的结果文件,两份格式都认得出,
    #    于是把「不适用」改判成「读不了」**结果一样不变**。
    #    > 一个「改坏了没红」和一个「这个改坏点在当下数据上观察不到」,
    #    > **在那句「改坏了却没红」上长得一模一样。**
    #    那两态由 `--自测` 的第 2–4 条守(造临时文件直接调那个函数)。
]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
FAIL = []


def ck(名, 真, 样本量, 说=""):
    记 = f"{G}✅{D}" if 真 else f"{R}❌{D}"
    print(f"  {记} {名}(验了 {样本量} 个)  {说}")
    if not 真:
        FAIL.append(名)


def 结果文件们(套):
    """**只扫这一套自己的**结果文件 —— 题号只在套内唯一。

    ⚠️ 第一版扫 `agent/**/*results.jsonl` 全部,**那是个真缺陷**:
    `growth` 套的结果里有 `G01`–`G08`,而 ops 的封存题里有 `G09` ——
    两者毫无关系,只是碰巧没撞上(growth 只有 8 道题)。
    **growth 加一道 G09,这条检查就会误报「ops 的封存题被跑了」**,
    而照着那条报警去查 ops 是白费功夫。
    > 一条「真的被跑了」和一条「别的套有个同名题号」,
    > **在那个交集上长得一模一样。**
    是咬合第三关把它逼出来的:攻击「封存题撞日常题号」时**红了两条**,
    多出来的那条就是这个误报(CLAUDE.md 第 8 节:红的必须是指定那一条)。
    """
    import glob
    pats = [os.path.join(ROOT, "agent", f"{套}-eval-results.jsonl"),
            os.path.join(ROOT, "agent", f"{套}-results.jsonl"),
            os.path.join(ROOT, "agent", "nightly", f"agent__{套}-eval-results.jsonl"),
            os.path.join(ROOT, "agent", "nightly", f"agent__{套}-results.jsonl")]
    out = []
    for x in pats:
        out += glob.glob(x)
    return sorted(set(out))


def 结果里的题号(路径):
    """→ (题号集合, 状态)。**状态有三种,不是两种。**

    ⚠️ 项目里那条规矩说「**没东西可验**必须和**验过了**分开」。
    第一版照做了,但只分了两态 —— 于是 12 份**本来就没有题号字段**的文件
    (消融实验 / 语音 / 三代对比)被判成「没验过」,一条检查红在 12 个无关文件上。
    而反过来把它们当成「干净」,就是把「没验过」读成了「验过了」。**两头都错。**

      · `"验了"`     —— 解析出题号,这份文件真验过
      · `"不适用"`   —— 每行都是合法 JSON,但**一个题号字段都没有**
                        → 它不是题集结果文件。**印出来**,不判红
                        (印出来是为了不让「不适用」变成囤积的豁免)
      · `"读不了"`   —— 文件打不开,或者**一行都解析不成 JSON** → 红
    """
    ids, 行数, 解析成功 = set(), 0, 0
    try:
        for ln in io.open(路径, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            行数 += 1
            try:
                d = json.loads(ln)
            except Exception:
                continue
            解析成功 += 1
            for k in ("id", "题号", "case", "题"):
                v = d.get(k)
                if isinstance(v, str) and v:
                    ids.add(v)
                    break
    except Exception:
        return set(), "读不了"
    if ids:
        return ids, "验了"
    if 行数 and 解析成功 == 0:
        return set(), "读不了"      # 有内容却一行都解析不了 —— 这才是「没验过」
    return set(), "不适用"           # 合法 JSON 但没有题号字段 → 不是题集结果


def main():
    print("封存题 · 检查")
    print("=" * 84)
    import ops_sealed as SE
    import ops_eval_judgetest as J

    封存 = [c["id"] for c in SE.SEALED]
    面 = SE.按面()

    # ── ① 样本量:一道都没找到 ≠ 都合规 ────────────────────────────────
    ck("找得到封存题(**一道都没找到不叫通过,叫没扫到东西**)", len(封存) > 0, len(封存),
       f"{len(封存)} 道封存题,分在 {len(面)} 个面上:"
       + "、".join(f"{k} {len(v)} 道" for k, v in sorted(面.items())))
    if not 封存:
        print(f"\n{R}❌ 封存题 1 处不符合预期{D}")
        sys.exit(1)

    # ── ② 每面正好 5 道(用户 2026-11-11 拍)────────────────────────────
    #    ⚠️ 这是**等号**不是下限:多了说明日常跑的那一面被挖空了,
    #    少了说明最终验收的样本不够。两边都要红。
    歪 = {k: len(v) for k, v in 面.items() if len(v) != SE.每面封存}
    ck(f"每面正好 {SE.每面封存} 道(用户 11-11 拍;**多了说明日常那面被挖空,少了说明验收样本不够**)",
       not 歪, len(面),
       f"{歪}" if 歪 else
       f"{len(面)} 个面各 {SE.每面封存} 道 —— 日常跑的那一面应是 16-{SE.每面封存}=11 道")

    # ── ③ 反向检查:封存题**不许出现在任何结果文件里** ──────────────────
    #    这是这条检查的承重墙。认不出格式的文件**单独报**,不算「干净」。
    犯规, 读不了, 不适用, 扫了 = {}, [], [], 0
    for p in 结果文件们(SE.套):
        ids, 状态 = 结果里的题号(p)
        rel = os.path.relpath(p, ROOT)
        if 状态 == "读不了":
            读不了.append(rel)
            continue
        if 状态 == "不适用":
            不适用.append(rel)
            continue
        扫了 += 1
        中 = sorted(set(封存) & ids)
        if 中:
            犯规[rel] = 中
    ck("封存题一道都没出现在结果文件里(**出现 = 这一面的最终验收已经失效**)",
       not 犯规, 扫了,
       (f"{犯规} —— 这些题说好不跑。**分数被看过之后它就只是验证集了**,"
        f"要么把那几行从结果里拿掉并说明为什么跑了它,要么把题从封存里挪出来"
        f"(别两边都不做:那样下次谁都不知道这一面还守不守得住)")
       if 犯规 else
       f"扫了 {扫了} 份 **{SE.套} 套自己的**结果文件(题号只在套内唯一,扫别的套会误报 —— growth 套就有 G01–G08),{len(封存)} 道封存题一道都没出现")
    # ⚠️ **「读不了」才红,「不适用」只印。** 见 `结果里的题号` 的 docstring:
    #    把这两件事合成一态,一边会拿 12 个无关文件去红,一边会把「没验过」读成干净。
    ck("没有读不了的结果文件(有内容却一行都解析不了 = 这份没被验过,不是干净)",
       not 读不了, len(读不了) or 1,
       f"{读不了[:4]} —— **这些文件没被验过**" if 读不了 else "没有读不了的")
    print(f"  ℹ️ 另有 {len(不适用)} 份**不适用**(合法 JSON 但没有题号字段,"
          f"不是题集结果):{', '.join(os.path.basename(x) for x in 不适用[:5])}"
          + (" …" if len(不适用) > 5 else "")
          + "\n     **印出来是为了不让「不适用」变成囤积的豁免** —— "
          "哪天某份题集结果掉进这一栏,这行字就是唯一的信号")

    # ── ④ 判据不能跟着题一起隐身 ──────────────────────────────────────
    有对照 = {t[1] for t in J.T}
    没对照 = [i for i in 封存 if i not in 有对照]
    ck("每道封存题都有对照(**判据从没被碰过和验过了,在解封那天之前一模一样**)",
       not 没对照, len(封存),
       f"{没对照} —— 给它们各补一条对照;**封存的是题,不是判据**"
       if 没对照 else f"{len(封存)} 道全部有对照")

    # ── ⑤ 反向的反向:封存题不许同时留在日常题集里 ──────────────────────
    #    ⚠️ 下一个人很可能把 SEALED import 进 CASES 图省事,
    #    那时隔离失效,**而门禁要等到跑评测那天才红**。
    import ops_eval as E
    日常 = {c["id"] for c in E.CASES}
    两边都在 = sorted(set(封存) & 日常)
    ck("封存题不在日常题集里(**同时在两边 = 隔离失效,而那要等跑评测那天才露出来**)",
       not 两边都在, len(日常),
       f"{两边都在} —— `ops_eval.CASES` 里还留着它们"
       if 两边都在 else f"日常 {len(日常)} 道、封存 {len(封存)} 道,**没有交集**")

    print()
    if FAIL:
        print(f"{R}❌ 封存题 {len(FAIL)} 处不符合预期{D}")
        for f in FAIL:
            print(f"   · {f}")
        sys.exit(1)
    print(f"{G}✅ 封存题符合预期{D}")
    print(f"    {len(封存)} 道故意不跑的题:"
          + "；".join(f"{k} = {'、'.join(v)}" for k, v in sorted(面.items())))
    print(f"    ⚠️ 它们**一道都没跑过**,难度未知 —— "
          f"解封时别把「判据分得开」读成「难度合适」。")


def 自测():
    """**咬合的离线一半**:拿造出来的形状去调上面那几个纯函数。

    ⚠️ 光验纯函数不够(CLAUDE.md 第 8 节 ⑥:用例全打在纯函数上而破坏点在接线上)——
    真正的咬合规格在 `tools/bite_specs.json` 里,它改**真文件**再重放整条检查。
    """
    print("封存题 · 自测")
    bad = 0
    import tempfile

    # ① 结果里的题号:认得出格式
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        f.write('{"id": "G09", "passed": true}\n{"id": "W01"}\n')
        p1 = f.name
    got = 结果里的题号(p1)
    ok = got == ({"G09", "W01"}, "验了")
    print(f"  {'✅' if ok else '❌'} 认得出 id 字段 → {got}")
    bad += not ok

    # ② **认不出格式要返回 None,不是空集** ——
    #    空集会被上面当成「这份文件干净」,而真相是「没验过」。
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        f.write('{"没有题号字段": 1}\n{"也没有": 2}\n')
        p2 = f.name
    got2 = 结果里的题号(p2)
    ok2 = got2 == (set(), "不适用")
    print(f"  {'✅' if ok2 else '❌'} 合法 JSON 但没题号字段 → {got2!r}"
          f"(**必须是「不适用」** —— 判成「读不了」会拿 12 个无关文件去红)")
    bad += not ok2

    # ③ 空文件也要返回 None(**没东西可验 ≠ 验过了**)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        p3 = f.name
    got3 = 结果里的题号(p3)
    ok3 = got3 == (set(), "不适用")
    print(f"  {'✅' if ok3 else '❌'} 空文件 → {got3!r}(没有内容 → 不适用)")
    # ④ **有内容却一行都解析不了 → 「读不了」,这才该红**
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        f.write("这不是 JSON\n这行也不是\n")
        p4 = f.name
    got4 = 结果里的题号(p4)
    ok4b = got4 == (set(), "读不了")
    print(f"  {'✅' if ok4b else '❌'} 有内容却解析不了 → {got4!r}"
          f"(**必须是「读不了」** —— 判成「不适用」就是把没验过读成干净)")
    bad += not ok4b
    try:
        os.unlink(p4)
    except OSError:
        pass
    bad += not ok3

    for p in (p1, p2, p3):
        try:
            os.unlink(p)
        except OSError:
            pass

    # ④ 按面():前缀分组
    import ops_sealed as SE
    面 = SE.按面()
    ok4 = all(all(i.startswith(k) for i in v) for k, v in 面.items())
    print(f"  {'✅' if ok4 else '❌'} 按面分组 → "
          + "、".join(f"{k}:{len(v)}" for k, v in sorted(面.items())))
    bad += not ok4

    # ⑤ **别的套的同名题号不算犯规** —— 这一条守的是上面那个真缺陷的修正。
    #    造一份 growth 套的结果文件、里面放一个 G09(ops 的封存题号),
    #    然后确认 `结果文件们("ops")` **不会把它捞进来**。
    import glob as _glob
    本套 = 结果文件们("ops")
    别套 = 结果文件们("growth")
    交 = set(本套) & set(别套)
    全部 = set(_glob.glob(os.path.join(ROOT, "agent", "*results.jsonl")))
    ok5 = (not 交) and 本套 and len(本套) < len(全部)
    print(f"  {'✅' if ok5 else '❌'} 只扫本套的结果文件 → ops {len(本套)} 份、"
          f"growth {len(别套)} 份、**没有交集**;全部 {len(全部)} 份里只取了 {len(本套)} 份"
          f"(**题号只在套内唯一** —— growth 套真有 G01–G08,"
          f"而 ops 的封存题里有 G09)")
    bad += not ok5

    print()
    if bad:
        print(f"{R}❌ 自测 {bad} 条不符合预期{D}")
        sys.exit(1)
    print(f"{G}✅ 自测 6 条全过{D}")


if __name__ == "__main__":
    if "--自测" in sys.argv:
        自测()
    else:
        main()
