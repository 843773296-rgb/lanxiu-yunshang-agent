#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具入参检查 —— **人怎么称呼一个东西,工具就得认得出来。**

## 为什么要有这条

一套 24 题的工具评测里,**4 条栽在同一件事上**:
顾问按日常说法问「PT04 马面裙推荐什么码」「PT06 立领长衫 M 码要多久」,
而 `kb_pattern` 只收**形制名**,于是一律回
「知识库里没有叫「PT04」的形制」—— **而 PT04 就在那张表里**。

最要命的是它**看起来像模型不行**:成绩单上是「没调 kb_fit」「没提到 162」,
读原话才知道模型说的是「查不到这个编码,请你确认」——
**它老老实实说查不到、要求补参数、没有编一个**,那正是对的行为。

> **工具的入参维度和人说话的维度对不上,表现出来是模型在胡说。**

## 这条检查验什么

库里同一个东西有**几套称呼**:版型有编码(PT04)、全名(明制马面裙·标准)、
变体名(阔褶马面裙);形制有编码(XZ03)、名字、别名(立领袄)。
**凡是人会用来称呼它的写法,查询工具都要认。**

只验「认不认得出」,不验返回内容 —— 内容那层有别的检查管。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE),
                os.path.join(os.path.dirname(HERE), "knowledge")]
import api

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row
    pats = [dict(r) for r in c.execute("SELECT code,name,xz FROM pattern")]
    xzs = [dict(r) for r in c.execute("SELECT code,name,alias FROM xingzhi")]

    # ① kb_pattern 要认:版型编码 / 版型全名 / 形制名 / 形制别名
    说法 = []
    for p in pats:
        说法 += [(p["code"], "版型编码"), (p["name"], "版型全名")]
    for z in xzs:
        说法.append((z["name"], "形制名"))
        for a in (z["alias"] or "").split("、"):
            if a.strip():
                说法.append((a.strip(), "形制别名"))
    坏 = []
    for q, 类 in 说法:
        r = api.kb_pattern(q)
        if r.get("error") or not r.get("rows"):
            坏.append(f"{类}「{q}」查不到")
    ck("kb_pattern 认得出人对版型的每一种称呼", not 坏, len(说法),
       ("；".join(坏[:3]) if 坏 else
        "**工具的入参维度和人说话的维度对不上,表现出来是模型在胡说** —— "
        "一套评测里 4 条栽在这上面"))

    # ② kb_size 同样要认编码和全名(它本来就两个都收,这条是**防回退**)
    坏2 = [f"{p['code']}/{p['name']}" for p in pats[:40]
           if api.kb_size(p["code"]).get("error")
           or api.kb_size(p["name"]).get("error")]
    ck("kb_size 认编码也认全名", not 坏2, min(40, len(pats)) * 2,
       ("；".join(坏2[:3]) if 坏2 else "已经支持 —— 这条是防回退"))

    # ③ **查不到的时候要说清这个工具认什么。**
    #    不说的话,模型只能反复猜入参,而每猜一次都是一轮对话和一次花费。
    e = api.kb_pattern("这个东西根本不存在").get("error") or ""
    ck("查不到时要说清这个工具认哪几种写法", "版型编码" in e, 1,
       "" if "版型编码" in e else f"报错里没说 —— 实际是:{e[:60]}")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 工具入参 3 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
