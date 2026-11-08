#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测题集导出 · 人造对照(离线、不读真库、不写真文件)。

## 它守的是什么

`tools/export_evals.py` 把跑出来的结果导成飞书上那份《评测题集》—— **用户唯一看得见
「这套题考了多少分」的地方**。2026-11-06 负向那套改成跑三轮之后发现它有个洞:
它按题号 `题[id] = r` 折叠,**同一道题的多轮结果只留最后一轮**。

> 一道「三轮都对」的题,和一道「前两轮错、最后一轮碰巧对」的题,
> **在这份导出的那个 ✅ 上长得一模一样** —— 而它们该触发的下一步动作相反:
> 前者是能力稳了,后者是要去查抖动。

同一个洞还有第二处:历次成绩的键是 `(套, 题, 跑于, 模型)`,**同一天的三轮是同一个键**,
于是历次表上「这天跑了三轮」和「这天跑了一轮」也长得一模一样。

## 两层,缺一不可

  ① 纯函数:直接喂 `一套()` 一个结果文件,看 `过 / 轮数 / 抖` 对不对
  ② **接线**:把 `ROOT / OUT` 指到临时目录,**真跑一遍 `main()`** ——
     验导出的 md 里那一栏真的逐轮印出来了。项目里那条:
     判据全打在纯函数上、而破坏点在接线上,**自测会全绿**。

跑:`python3 tools/export_evals_test.py`
"""
# 咬合 —— 改坏的是什么、该红的是哪一条。可执行规格在 `tools/bite_specs.json`,三条都真跑过三关。
咬合 = [
    ("把「全部轮次都对才算对」改回「只看最后一轮」(老那个洞)",
     "只有最后一轮对的题被算成了对"),
    ("把历次成绩的键里的轮号去掉 —— 同一天三轮又变成同一个键",
     "同一天的三轮在历次里只留下"),
    ("让导出的逐轮那一栏只印最后一轮(破坏点在渲染那根线上,不在纯函数里)",
     "逐轮那一栏只印了一个格子"),
    ("让「这套有没有对错这个概念」恒真 —— 没有真值的那套会被印成 0/20",
     "没有真值的那套被印成了全错"),
]

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import export_evals as E          # noqa: E402

挂 = []


def ck(条件, 名, 实际=""):
    print(f"  {'✅' if 条件 else '❌'} {名}" + (f"  —— {实际}" if 实际 and not 条件 else ""))
    if not 条件:
        挂.append(名)


def 写(目录, 名, 行们):
    fp = os.path.join(目录, f"{名}-results.jsonl")
    with open(fp, "w", encoding="utf-8") as fh:
        for r in 行们:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return fp


def 题(id, 轮, 过, **kw):
    d = dict(id=id, prompt=f"题面 {id}", passed=过, kind="negative",
             模型="假模型", 跑于=f"2026-11-06 0{轮}:00:00")
    if 轮 is not None:
        d["轮"] = 轮
    d.update(kw)
    return d


def main():
    print("评测题集导出 · 人造对照")
    tmp = tempfile.mkdtemp(prefix="exportevals-")
    try:
        # ───────── 第一层:纯函数 ─────────
        print("\n① 单轮的那几套:行为必须一个字没变")
        f = 写(tmp, "单", [题("A", None, True), 题("B", None, False), 题("C", None, True)])
        s = E.一套(f)
        ck(len(s["题"]) == 3, "① 单轮 · 三题都在", f"{len(s['题'])} 题")
        ck(s["过"] == 2, "① 单轮 · 判对 2/3", f"过={s['过']}")
        ck(s["轮数"] == 1, "① 单轮 · 轮数报 1", f"轮数={s['轮数']}")
        ck(s["抖"] == [], "① 单轮 · 没有轮间翻面可报", f"抖={s['抖']}")

        print("\n② 多轮:**全轮都对才算对**(这是修掉的那个洞)")
        f = 写(tmp, "多", [题("N1", 1, True), 题("N1", 2, True), 题("N1", 3, True),
                          题("N2", 1, False), 题("N2", 2, False), 题("N2", 3, True),
                          题("N3", 1, True), 题("N3", 2, False), 题("N3", 3, False)])
        s = E.一套(f)
        ck(s["轮数"] == 3, "② 多轮 · 轮数报 3", f"轮数={s['轮数']}")
        ck(len(s["题"]) == 3, "② 多轮 · 三道题,不是九道", f"{len(s['题'])} 题")
        ck(s["过"] == 1,
           "② 多轮 · 只有 N1 算对 —— 三轮里只有最后一轮对的题被算成了对就是老那个洞",
           f"过={s['过']},该是 1")
        ck(s["抖"] == ["N2", "N3"], "② 多轮 · 翻过面的两道都点出来", f"抖={s['抖']}")
        ck([x.get("passed") for x in s["轮们"]["N2"]] == [False, False, True],
           "② 多轮 · 每一轮的结果都留着(不是只留最后一轮)",
           str([x.get("passed") for x in s["轮们"]["N2"]]))

        print("\n③ 落盘顺序乱了也要按轮号排")
        f = 写(tmp, "乱", [题("X", 3, True), 题("X", 1, True), 题("X", 2, False)])
        s = E.一套(f)
        ck([x["轮"] for x in s["轮们"]["X"]] == [1, 2, 3], "③ 按轮号排序,不按文件顺序",
           str([x["轮"] for x in s["轮们"]["X"]]))
        ck(s["过"] == 0, "③ 中间那轮错了就不算对", f"过={s['过']}")

        print("\n④ 没有题号的那几套(wild-run 形状):20 行就是 20 题")
        f = 写(tmp, "无号", [dict(q=f"第 {i} 问", passed=True) for i in range(20)])
        s = E.一套(f)
        ck(len(s["题"]) == 20, "④ 20 行导成 20 题 —— 原来用字典长度当键会互相顶掉",
           f"{len(s['题'])} 题")

        print("\n④·2 不按对错判的那套(野外巡检:真实语料,没有真值)")
        f = 写(tmp, "野", [dict(q=f"第 {i} 问", 一致=False) for i in range(20)])
        s2 = E.一套(f)
        ck(s2["有判"] is False, "④·2 认出这套没有 passed 这一栏", f"有判={s2['有判']}")
        ck(s2["过"] is None,
           "④·2 判对那一栏给 None —— 没有真值的那套被印成了全错(0/20)就是那个洞",
           f"过={s2['过']}")

        # ───────── 历次成绩 ─────────
        print("\n⑤ 历次成绩:同一天的每一轮各记一条")
        站 = os.path.join(tmp, "站")
        os.makedirs(os.path.join(站, "agent"), exist_ok=True)
        真ROOT = E.ROOT
        E.ROOT = 站
        try:
            f = 写(os.path.join(站, "agent"), "多",
                   [题("N1", 1, True), 题("N1", 2, False), 题("N1", 3, True)])
            套 = [E.一套(f)]
            按题, 按套 = E.历次(套)
            键们 = [k for k in 按套 if k[0] == "多"]
            ck(len(键们) == 3,
               "⑤ 同一天的三轮在历次里只留下一条就是第二处洞 —— 这里要三条",
               f"{len(键们)} 条:{键们}")
            ck(sorted(k[2] for k in 键们) == [1, 2, 3], "⑤ 三条各带自己的轮号",
               str(sorted(k[2] for k in 键们)))
            ck(len(按题[("多", "N1")]) == 3, "⑤ 按题也能看到三轮",
               str(len(按题[("多", "N1")])))
            行数 = len(open(os.path.join(站, "agent", "eval-history.jsonl"),
                           encoding="utf-8").read().strip().splitlines())
            E.历次(套)                      # 再来一遍
            行数2 = len(open(os.path.join(站, "agent", "eval-history.jsonl"),
                            encoding="utf-8").read().strip().splitlines())
            ck(行数 == 3 and 行数2 == 3, "⑤ 重跑一遍不重复记账", f"{行数} → {行数2}")
        finally:
            E.ROOT = 真ROOT

        # ───────── 第二层:接线(真跑 main) ─────────
        print("\n⑥ 接线:真跑一遍 main(),看导出的 md 里逐轮那一栏")
        站2 = os.path.join(tmp, "站2")
        os.makedirs(os.path.join(站2, "agent"), exist_ok=True)
        写(os.path.join(站2, "agent"), "多",
          [题("N1", 1, True, 内容对=True, 协议走=True),
           题("N1", 2, True, 内容对=True, 协议走=True),
           题("N2", 1, False, 内容对=True, 协议走=False, why=["没交草稿"]),
           题("N2", 2, True, 内容对=True, 协议走=True)])
        写(os.path.join(站2, "agent"), "野", [dict(q="没有真值的一句话", 一致=True)])
        真ROOT, 真OUT = E.ROOT, E.OUT
        E.ROOT = 站2
        E.OUT = os.path.join(站2, "题集.md")
        try:
            E.main()
            md = open(E.OUT, encoding="utf-8").read()
        finally:
            E.ROOT, E.OUT = 真ROOT, 真OUT
        ck("❌✅" in md,
           "⑥ 接线 · N2 那道印出「❌✅」—— 逐轮那一栏只印了一个格子就是渲染那根线断了",
           "md 里找不到「❌✅」")
        ck("✅✅" in md, "⑥ 接线 · N1 那道印出「✅✅」", "md 里找不到「✅✅」")
        ck("第 1 轮" in md and "第 2 轮" in md, "⑥ 接线 · 历次表里两轮各占一行")
        ck("内容对" in md and "协议走" in md, "⑥ 接线 · 两个数分开印,没合成一个")
        ck("1/2" in md, "⑥ 接线 · 总表判对是 1/2(N2 翻过面不算对)")
        ck("不按对错判" in md and "0/1" not in md,
           "⑥ 接线 · 野跑那套印「不按对错判」,不印成 0/1",
           "md 里没有「不按对错判」或者出现了 0/1")

        # ───────── 第三层:技能触发那套(结果在 agentsite/evals/runs/,格式不同)─────────
        # ⚠️ 这一节是补的:加完接入之后跑自测,它**绿了**,而绿的理由是
        # 临时目录里没有 runs/ 文件、**那条路径一次都没被执行**。
        # > 一条「这套渲染是对的」的绿勾,和一条「这套渲染一次都没跑到」的绿勾,
        # > 在那个 ✅ 上长得一模一样。
        # (看见它的唯一原因是 main 里那句 ℹ️「没东西可导」老实印出来了。)
        print("\n⑦ 技能触发那套:只有汇总怎么印、没盖章怎么排除、有逐轮怎么印")
        站3 = os.path.join(tmp, "站3")
        runs3 = os.path.join(站3, "agentsite", "evals", "runs")
        os.makedirs(os.path.join(站3, "agent"), exist_ok=True)
        os.makedirs(runs3, exist_ok=True)
        写(os.path.join(站3, "agent"), "多", [题("N1", 1, True), 题("N1", 2, True)])

        def 存基线(名, 跑于, 明细, 遍数=5, 模型="claude-sonnet-5", 盖章=True):
            d = {"准确率": f"{sum(1 for x in 明细 if x.get('ok'))}/{len(明细)}",
                 "重复遍数": 遍数, "明细": 明细}
            if 盖章:
                d["来路"] = {"跑于": 跑于, "模型": 模型, "供应商": "claude"}
            with open(os.path.join(runs3, f"{名}.json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)

        def 条(i, want, hits, runs, 逐轮=None):
            x = dict(id=i, prompt=f"第 {i} 问", want=want,
                     got=want if hits == runs else (f"{want}?2种" if want else None),
                     ok=(hits == runs), kind="对" if hits == runs else "不稳定",
                     hits=hits, runs=runs, wobbly=(0 < hits < runs))
            if 逐轮 is not None:
                x["逐轮"] = 逐轮
            return x

        汇总 = [条(1, "quote", 5, 5), 条(2, "quote", 4, 5), 条(3, None, 5, 5)]
        存基线("v7", "2026-11-01 10:00:00", 汇总, 模型="claude-haiku-4-5")
        存基线("v8", "2026-11-02 10:00:00", 汇总)
        # ⚠️ 没盖来路章,而版本号最大、跑于还最新 —— 它**不许**被选中,也不许进历次表。
        # runs/ 里真的混着十个这样的实验文件,其中一个就叫 `v54.json`(24 条的实验,
        # 不是「第 54 版」)—— 一个「第 54 版基线」和一个「叫 v54 的实验文件」,
        # 在文件名上长得一模一样。
        存基线("v88", "2026-11-09 10:00:00", 汇总, 盖章=False)
        真ROOT, 真OUT = E.ROOT, E.OUT
        E.ROOT, E.OUT = 站3, os.path.join(站3, "题集.md")
        try:
            E.main()
            md3 = open(E.OUT, encoding="utf-8").read()
        finally:
            E.ROOT, E.OUT = 真ROOT, 真OUT
        ck("技能触发" in md3, "⑦ 这套真的进了导出(此前整套不在)", "md 里没有「技能触发」")
        ck("4/5 次对" in md3,
           "⑦ 只有汇总的那一版,逐轮那栏印「4/5 次对」(不是一个光秃秃的 ❌)",
           "md 里找不到「4/5 次对」")
        ck("只存了汇总" in md3,
           "⑦ 明说这一版没存是哪一遍错的 —— **「没存逐轮」和「没抖」不是一回事**",
           "md 里没有那句提醒")
        ck("`v7`" in md3 and "`v8`" in md3, "⑦ 历次表把盖过章的两版都列出来")
        ck("`v88`" not in md3,
           "⑦ 没盖来路章的不进历次表(版本号最大、跑于最新也不算基线)",
           "v88 混进去了")
        ck("claude-haiku-4-5" in md3 and "claude-sonnet-5" in md3,
           "⑦ 历次表每行带**模型** —— 少了它,换模型那一跳会被读成「能力涨了」",
           "md 里缺模型那一栏")
        ck("不该触发任何技能" in md3,
           "⑦ 负向题(want 为空)的标准答案印出来了", "md 里没有那句")
        # 有逐轮的那一版:印一串 ✅❌,而且那句「只存了汇总」要消失
        存基线("v9", "2026-11-03 10:00:00",
               [条(1, "quote", 5, 5, 逐轮=["quote"] * 5),
                条(2, "quote", 3, 5, 逐轮=["quote", None, "quote", "quote", None])])
        E.ROOT, E.OUT = 站3, os.path.join(站3, "题集2.md")
        try:
            E.main()
            md4 = open(E.OUT, encoding="utf-8").read()
        finally:
            E.ROOT, E.OUT = 真ROOT, 真OUT
        ck("✅❌✅✅❌" in md4,
           "⑦ 有逐轮的那一版**逐遍印**(三个 ✅ 和「❌❌✅」在一个 ✅ 上分不开)",
           "md 里找不到那一串")
        ck("只存了汇总" not in md4,
           "⑦ 有逐轮之后,那句「只存了汇总」的提醒不再印(不然它会变成一句假话)",
           "有逐轮了还在印那句")

        print("\n" + ("❌ 挂了 %d 条:%s" % (len(挂), "、".join(挂)) if 挂
                      else "✅ 全部符合预期"))
        return 1 if 挂 else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
