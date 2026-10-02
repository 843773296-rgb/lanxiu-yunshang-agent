#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库扩容(知识库 E)· 检查 —— **扩的每一条都说得出回答了谁的什么问题,而且有出处。**

intent `kb-e-staff-training`:业务要把给人读的知识扩到 20 万 token(表格不算,业务 09-25)。
最大的风险写在 intent 里:**一篇注了水的和一篇扎实的,在字符数上长得一模一样。**
所以扩容内容一律写成「讲给顾客听」的详解条目,每条必须带:

    回答的问题  顾客 / 店员真会问的那一句(判据 ⑤:说得出它回答了哪个具体问题)
    要点        页面上原样有的事实(数字要在页面上 —— verify_sources 联网核,不进门禁)
    讲法        改写给顾客听的话
    来源类型 / 抓取日期 / 出处(出处名:页面标题 → 链接)

这里管不联网的那几样,外加一条结构性的:**详解不许漏进工艺表**
(`kb.load()` 遇到不带编号的 `##` 就收尾;哪天有人把详解写进了带编号的条目里,
它会被并进 craft 表的 detail 栏、截断在 600 字,而且把原来的非遗出处覆盖掉)。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

咬合 = [
    ("把一条详解的「回答的问题」删掉", "每条详解都带齐六样"),
    ("把一条详解标题末尾的 `public` 去掉", "每条详解标题都标了来源等级"),
    # ⚠️ 第一版的破坏点是「删掉详解那一节的二级标题」—— 没红:解析器遇到不带编号的 `###` 也会收尾,
    # 那样本来就漏不进去(破坏点不可观测)。真会漏的是**把详解字段写进带编号的条目里**
    ("把一条详解的「讲法」写进带编号的工艺条目里(KF01 缂丝)", "详解没有漏进工艺表"),
]

必填 = ("回答的问题", "要点", "讲法", "来源类型", "抓取日期", "出处")
节名 = "讲给顾客听"
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 详解条目():
    """各篇里「讲给顾客听」那一节的 `### ` 条目 → [(文件, 标题行, {字段: 值})]。"""
    out = []
    for f in sorted(os.listdir(os.path.join(ROOT, "knowledge"))):
        if not f.endswith(".md"): continue
        在节, cur = False, None
        for l in open(os.path.join(ROOT, "knowledge", f), encoding="utf-8"):
            l = l.rstrip("\n")
            if l.startswith("## "):
                在节, cur = 节名 in l, None
                continue
            if not 在节: continue
            if l.startswith("### "):
                cur = (f, l, {}); out.append(cur); continue
            m = re.match(r"^-\s*(?:\*\*)?(回答的问题|要点|讲法|来源类型|抓取日期|出处)(?:\*\*)?\s*[::]\s*(.+)$", l.strip())
            if cur and m:
                cur[2][m.group(1)] = m.group(2).strip()
    return out


def main():
    print("知识库扩容 · 检查")
    print("=" * 84)
    es = 详解条目()
    缺 = [f"{f}「{t[4:24]}」缺{'、'.join(k for k in 必填 if not d.get(k))}"
         for f, t, d in es if any(not d.get(k) for k in 必填)]
    ck("每条详解都带齐六样(回答的问题 / 要点 / 讲法 / 来源类型 / 抓取日期 / 出处)", not 缺, len(es),
       f"共 {len(缺)} 条:" + "；".join(缺[:3]) if 缺 else f"{len(es)} 条")
    无标 = [f"{f}「{t[4:24]}」" for f, t, _ in es if not re.search(r"`(public|scale|demo)`\s*$", t)]
    ck("每条详解标题都标了来源等级(kb_read 按它给对客口径)", not 无标, len(es),
       f"共 {len(无标)} 条:" + "、".join(无标[:3]) if 无标 else "")
    问 = [d.get("回答的问题", "") for _, _, d in es]
    空问 = [q for q in 问 if not re.search(r"「.+」", q)]
    ck("「回答的问题」写的是一句具体的问话(带引号),不是一个话题", not 空问, len(问),
       f"共 {len(空问)} 条:" + "、".join(空问[:3]) if 空问 else "")
    import kb
    漏 = [r[0] for r in kb.load() if r[5] and any(f"{k}:" in r[5] for k in ("回答的问题", "讲法"))]
    ck("详解没有漏进工艺表(kb.load 解析出的条目里没有详解字段)", not 漏, len(kb.load()),
       f"共 {len(漏)} 条:{漏[:5]}" if 漏 else "")
    import api
    篇们 = sorted({f for f, _, _ in es})
    读不到 = [f for f in 篇们 if not any(节名 in x["标题"] for x in (api.kb_read(f[:2]).get("小节") or []))]
    ck("每篇的详解那一节 kb_read 读得到", not 读不到, len(篇们), "、".join(读不到))

    print()
    if FAIL:
        print(f"\033[31m❌ 知识库扩容 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 知识库扩容全部符合预期\033[0m({len(es)} 条详解,{len(篇们)} 篇)")


if __name__ == "__main__":
    main()
