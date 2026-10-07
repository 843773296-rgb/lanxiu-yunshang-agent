#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**把几个切片拆成独立文档** —— 这个动作的判定,零 IO。

业务 2026-10-07 拍了「切片级权限不做,要收紧就拆成独立文档」。那一拍省掉了
一套切片级 ACL,代价全压在这个动作上 —— 下面每一条对着一种**拆完看起来对了
而实际没收紧**的方式:

   ① 新文档权限留空继承 / 子集检查漏了 → 拆分成了一条放宽的路子
   ② 整篇拆走(留一篇空文档)/ 野 id 跳过(拆出一篇少几段的文档)
   ③ 搬过去的片段重切 → **整个知识库从此建不出索引**(下次重建才炸)
   ④ `欠账` 为空 → 调用方拿到一个能当「做完了」用的返回值
   ⑤ 片段清单本身:重复 id 去重、缺 ordinal、空清单
   ⑥ **不重不漏** —— 搬走的 ∪ 留下的 == 全部,且交集为空

## ⚠️ 第 ⑥ 节是这一组存在的主要理由

> 一次「把那几段**拆走**了」的拆分,和一次「把那几段**复制**过去、
> 而原文档也还留着」的,**在新文档的片段列表上长得一模一样** ——
> 两边都有那几段正文、都排好了序号、权限也都设对了。
> 而后者**权限白收紧了**:那个人照旧从原文档检索得到。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "contract"))

import 拆文档 as S
import 语料可见 as V

G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = 0, 0


def ck(说, ok, 附=""):
    global 过, 挂
    if ok:
        过 += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        挂 += 1
        print(f"  {R}❌{D} {说}  {附}")


def 抛(说, f, 要含=()):
    """f() 该抛 `拆不了`,而且理由里要含这几个词。"""
    global 过, 挂
    try:
        f()
    except S.判不了 as e:
        缺 = [w for w in 要含 if w not in str(e)]
        if 缺:
            挂 += 1
            print(f"  {R}❌{D} {说} —— 抛了,但理由里没提 {缺}\n      「{e}」")
        else:
            过 += 1
            print(f"  {G}✅{D} {说}\n      「{str(e)[:150]}」")
    except Exception as e:
        挂 += 1
        print(f"  {R}❌{D} {说} —— 抛的是 {type(e).__name__} 不是 拆不了:{e}")
    else:
        挂 += 1
        print(f"  {R}❌{D} {说} —— **没抛**")


def 段(i, ordinal, 切="seg-1", 解="md-1"):
    return dict(id=i, ordinal=ordinal, chunker_version=切, parser_version=解,
                text_hash=f"h{i}", section_path=f"第{ordinal}节",
                section_titles=[f"第{ordinal}节"])


十段 = [段(f"c{n}", n) for n in range(10)]
宽 = ["viewer", "editor", "approver", "admin"]

print("=" * 92)
print("拆成独立文档 —— 这个动作的判定")
print("=" * 92)

print("\n▸ ① 新文档的权限:必填、写死、且必须是源文档有效范围的子集")

抛("新文档 ACL 留空 → 拒(空在 `语料可见` 那边是「继承知识库」,"
   "而新文档可能落在另一个库里)",
   lambda: S.定(源文档片段=十段, 要拆走的id们=["c1"], 源知识库acl=宽,
               目标知识库acl=宽, 新文档acl=None),
   ("不许留空", "长得一模一样"))

抛("新文档想放宽(源文档有效范围只到 admin,新的要 editor)→ 拒",
   lambda: S.定(源文档片段=十段, 要拆走的id们=["c1"],
               源知识库acl=["admin"], 源文档acl=None,
               目标知识库acl=宽, 新文档acl=["editor", "admin"]),
   ("收紧", "editor", "另一个动作"))

抛("放宽的理由里要**点名多出来的是谁**,不是一句「权限设置失败」",
   lambda: S.定(源文档片段=十段, 要拆走的id们=["c1"],
               源知识库acl=宽, 源文档acl=["admin"],
               目标知识库acl=宽, 新文档acl=["approver", "admin"]),
   ("approver",))

p = S.定(源文档片段=十段, 要拆走的id们=["c1", "c2"],
        源知识库acl=宽, 源文档acl=["editor", "admin"],
        目标知识库acl=宽, 新文档acl=["admin"], 目标知识库id="kb-1")
ck("收紧(源 {editor,admin} → 新 {admin})放行",
   p["权限"]["新文档范围"] == ["admin"], p["权限"]["新文档范围"])
ck("新文档的 `acl_override` 是**写死的字面量**,不是 None",
   p["新文档"]["acl_override"] == {"roles": ["admin"]},
   p["新文档"]["acl_override"])
ck("🔑 对照:同范围(不收紧也不放宽)也放行 —— 拆分不强制一定要收紧",
   S.定(源文档片段=十段, 要拆走的id们=["c1"], 源知识库acl=["admin"],
        目标知识库acl=["admin"], 新文档acl=["admin"]
        )["权限"]["新文档范围"] == ["admin"])
ck("和 `语料可见` 用的是同一个口径(源范围 == 它算的)",
   p["权限"]["源文档有效范围"]
   == sorted(V.定(知识库acl=宽, 文档acl=["editor", "admin"])[0]))
ck("认不出的角色名由 `语料可见` 那边当场抛(不在这儿重写一遍判定)",
   isinstance(S.判不了("x"), V.判不了))

print("\n▸ ② 拆的范围:整篇不是拆分 · 野 id 当场抛")

抛("整篇都拆走 → 拒(那是改这篇文档本身的权限,照拆会留一篇 0 段空文档)",
   lambda: S.定(源文档片段=十段, 要拆走的id们=[x["id"] for x in 十段],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("不是拆分", "acl_override", "空文档"))

抛("要拆的 id 不在这篇文档最新那一版里 → **当场抛,不跳过**",
   lambda: S.定(源文档片段=十段, 要拆走的id们=["c1", "不存在的"],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("不跳过", "选错了文档", "max(revision)"))

抛("一段都没选 → 拒,不兜底成「那就不拆」",
   lambda: S.定(源文档片段=十段, 要拆走的id们=[],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("不兜底",))

抛("要拆的 id 写了两次 → 拒,**不去重**",
   lambda: S.定(源文档片段=十段, 要拆走的id们=["c1", "c1"],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("不去重",))

ck("🔑 对照:只拆走 9 段中的 9 段里的 9 段 —— 留 1 段就放行",
   len(S.定(源文档片段=十段, 要拆走的id们=[x["id"] for x in 十段[:9]],
           源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]
           )["原文档留下的片段"]) == 1)

print("\n▸ ③ 切片器版本:沿用源片段记着的,不读当前常量")

ck("搬过去的片段带的是**源片段的** chunker_version",
   all(x["chunker_version"] == "seg-1" for x in p["搬过去的片段"]),
   [x["chunker_version"] for x in p["搬过去的片段"]])

旧 = [段("a0", 0, 切="seg-0", 解="md-0"), 段("a1", 1, 切="seg-0", 解="md-0"),
     段("a2", 2, 切="seg-0", 解="md-0")]
q = S.定(源文档片段=旧, 要拆走的id们=["a1"], 源知识库acl=宽,
        目标知识库acl=宽, 新文档acl=["admin"])
ck("🔑 **源是 seg-0 时搬过去的也必须是 seg-0** —— 这一条才真的拦住"
   "「读当前常量」(上面那条 seg-1 恰好可能和常量相同)",
   [x["chunker_version"] for x in q["搬过去的片段"]] == ["seg-0"],
   [x["chunker_version"] for x in q["搬过去的片段"]])
ck("解析器版本同样沿用",
   [x["parser_version"] for x in q["搬过去的片段"]] == ["md-0"])
ck("模块里一个 chunker 版本字面量都不写死(写了就是在造当前常量)",
   not any(s in open(os.path.join(
       _根, "services", "api", "app", "runtime", "拆文档.py"),
       encoding="utf-8").read().split('"""', 2)[2]
       for s in ("seg-1", "seg-2", "md-1")))

混 = [段("m0", 0, 切="seg-1"), 段("m1", 1, 切="seg-2"), 段("m2", 2, 切="seg-1")]
r = S.定(源文档片段=混, 要拆走的id们=["m0", "m1"], 源知识库acl=宽,
        目标知识库acl=宽, 新文档acl=["admin"])
ck("混着切的片段**不抛** —— 拆得了,只是做完那个库建不出索引,"
   "抛了会让人无路可走",
   isinstance(r, dict))
ck("而它进 `欠账`,并点名 MIXED_CHUNKER_VERSION 是**整个知识库**一起查的",
   any("MIXED_CHUNKER_VERSION" in x and "整个知识库" in x for x in r["欠账"]),
   r["欠账"][0][:70])
ck("`版本们()` 保留 None,不折叠成「和当前一样」",
   S.版本们([段("z", 0, 切=None, 解=None)]) == [(None, None)])

print("\n▸ ④ 拆完还没生效:`欠账` 必须非空")

ck("`欠账` 非空",
   bool(p["欠账"]), f"{len(p['欠账'])} 条")
ck("里头点名了「在役索引是快照」这件事",
   any("快照" in x and "index_build" in x for x in p["欠账"]))
ck("也点名了 `content_hash` 不许照抄上一版",
   any("content_hash" in x and "不能照抄" in x for x in p["欠账"]))
ck("返回里没有任何能当「成功 / 做完了」用的键",
   not ({"成功", "ok", "done", "已生效", "结果"} & set(p)), sorted(p))
ck("原文档新版本的 source_info 标成派生,不是解析得出的",
   p["原文档新版本"]["source_info"]["存储"] == S.派生自拆分)
ck("新版本的 object_key 是 None(它解析不出来),而原文档照抄上一版",
   p["新版本"]["object_key"] is None
   and "照抄" in str(p["原文档新版本"]["object_key"]))

print("\n▸ ⑤ 片段清单本身")

抛("源文档一个片段都没有 → 拒",
   lambda: S.定(源文档片段=[], 要拆走的id们=["c1"], 源知识库acl=宽,
               目标知识库acl=宽, 新文档acl=["admin"]),
   ("不兜底",))
抛("源片段里有重复 id → 拒(去重会让「选了 3 段」变成「拆走 2 段」)",
   lambda: S.定(源文档片段=十段 + [段("c1", 11)], 要拆走的id们=["c2"],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("两次", "不去重"))
抛("源片段缺 ordinal → 拒(拆出来要重排序号,排不了)",
   lambda: S.定(源文档片段=[dict(id="x")], 要拆走的id们=["x"],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("ordinal",))
抛("片段不是 dict → 拒",
   lambda: S.定(源文档片段=["c0", "c1"], 要拆走的id们=["c0"],
               源知识库acl=宽, 目标知识库acl=宽, 新文档acl=["admin"]),
   ("dict",))

print("\n▸ ⑥ 不重不漏 —— 这一组的主要理由")

for n, 拆谁 in enumerate([["c0"], ["c9"], ["c3", "c4"], ["c0", "c5", "c9"],
                        [x["id"] for x in 十段[:-1]]]):
    g = S.定(源文档片段=十段, 要拆走的id们=拆谁, 源知识库acl=宽,
            目标知识库acl=宽, 新文档acl=["admin"])
    走 = {x["源片段id"] for x in g["搬过去的片段"]}
    留 = {x["源片段id"] for x in g["原文档留下的片段"]}
    ck(f"拆 {拆谁 if len(拆谁) < 4 else f'{len(拆谁)} 段'}:"
       f"走 ∪ 留 == 全部,且**交集为空**",
       走 | 留 == {x["id"] for x in 十段} and not (走 & 留),
       f"走 {len(走)} / 留 {len(留)} / 交 {sorted(走 & 留)}")
    ck(f"  走的正好是点名的那几段", 走 == set(拆谁))
    ck(f"  两边 ordinal 都重排成 0..n-1 连续",
       [x["新ordinal"] for x in g["搬过去的片段"]] == list(range(len(走)))
       and [x["新ordinal"] for x in g["原文档留下的片段"]] == list(range(len(留))))
    ck(f"  重排后仍保持原相对顺序",
       [x["原ordinal"] for x in g["搬过去的片段"]]
       == sorted(x["原ordinal"] for x in g["搬过去的片段"])
       and [x["原ordinal"] for x in g["原文档留下的片段"]]
       == sorted(x["原ordinal"] for x in g["原文档留下的片段"]))

ck("🔑 对照:**如果实现改成「复制而不移走」,第 ⑥ 节会红** —— "
   "那时 走 ∪ 留 仍 == 全部,而 走 & 留 非空",
   True, "(这条是说明判据为什么设计成交集,不是断言)")

print("\n▸ ⑦ 不假装解决的事")
ck("文档里写清了这是召回层的权限(和 `语料可见` 同一条)",
   "召回层" in (S.__doc__ or ""))
ck("写清了原切片一条都不动(不可变、证据链)",
   "一条都不动" in (S.__doc__ or "") and "证据链" in (S.__doc__ or ""))
ck("写清了「拆完还没生效」,而不是让调用方自己想到",
   "还没生效" in (S.__doc__ or ""))

print("\n" + "=" * 92)
if 挂:
    print(f"{R}❌ 过 {过} / 挂 {挂}{D}")
    sys.exit(1)
print(f"{G}✅ 过 {过} / 挂 {挂}{D}")
