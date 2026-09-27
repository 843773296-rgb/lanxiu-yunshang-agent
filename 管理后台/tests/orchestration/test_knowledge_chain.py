#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识链:解析 + 切片 —— **判据是「证据链真的能指回原文」**。

## 这一层为什么值得单独测,而且判据要这么定

规格 §19.4 给 `DocumentParser` 那一行写了一句话:

> **source_location 是证据链的一环**:片段要能指回原文第几页第几段,
> **否则「有出处」只是一句话**。

所以这里最重要的那条断言不是「切出了几块」,是:
**拿着片段记的位置回原文找,能不能找到那段原文。**

一个返回 `节路径="某节"` 而原文里没有那一节的解析器,
在片段的数据形状上和正确的解析器**一模一样** —— 而它产出的每一条引用都是假的。

## 判据用真语料,不用我编的 Markdown

用 `业务决策/业务拍板-*.md`(澜绣的真拍板记录)。理由:我编的夹具会**照着实现编**
—— 我知道解析器怎么处理标题,于是编出来的夹具正好是它处理得好的那种。
真语料里有我没预料的形状(引用块、表格、⚠️ 开头的段、代码围栏),
**而那些形状才是会出错的地方**。

⚠️ 代价写清楚:真语料**会变**(业务每天拍板)。所以断言**不钉具体数字**
(不写「切出 8 个片段」),只钉**性质**:每个片段的位置都能在原文里找到、
节路径是原文里真实存在的标题、合并只在同一节内发生。
性质对数据变化不敏感,而数字每天都要改一次 —— 而每天要改的断言最后会被删掉。
"""
import os
import re
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
澜绣 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app", "knowledge"))
import parser as P  # noqa: E402
import chunker as C  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:180] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


语料目录 = os.path.join(澜绣, "业务决策")
文件们 = sorted(f for f in os.listdir(语料目录) if f.endswith(".md")) \
    if os.path.isdir(语料目录) else []
ck("找到真语料(澜绣的业务拍板记录)", len(文件们) >= 3, len(文件们), 文件们[:4])

print("\n▸ ① 证据链:**拿片段记的位置回原文找,必须找得到**")
坏位置, 坏节, 总片段 = [], [], 0
for f in 文件们:
    原 = open(os.path.join(语料目录, f), encoding="utf-8").read()
    r = C.切(P.解析(原, 文件名=f), 文档版本id=f"dv_{f}")
    标题们 = {t for _, t in P._所有标题(原)}
    for c in r["片段们"]:
        总片段 += 1
        # 节路径里每一级都必须是原文里**真实存在**的标题
        for 级 in c["section_path"].split(" / "):
            if 级 != "(正文开头)" and 级 not in 标题们:
                坏节.append((f, 级))
        # 片段正文必须**真的出现在原文里**(合并只是拼接,不该改写)
        for 行 in c["text"].splitlines():
            if 行.strip() and 行.strip() not in 原:
                坏位置.append((f, 行.strip()[:30]))
                break
ck("**每个片段的节路径都是原文里真实存在的标题**"
   "(返回一个原文没有的节名,数据形状上看不出来)",
   not 坏节, 总片段, 坏节[:3])
ck("**片段正文原样出现在原文里**(合并只拼接,不改写 —— 改写过的引用核不回去)",
   not 坏位置, 总片段, 坏位置[:2])

print("\n▸ ② 合并只在同一节内(跨节合并会造出「横跨两个决定」的片段)")
# ⚠️ **判据换过两次依据,两次都是咬合逼出来的。**
#   第一版判「片段的段序号都属于它那一节」—— 抓不住跨节合并:
#     **段序号在节内重新编**,跨节合并出来的 `[3, 1]` 里那个「第 1 段」
#     在它记的那一节里确实存在,判据放行。
#   第二版改成「拿片段的每一行回原文 find(),看它落在哪一节」—— **误报**:
#     `|---|---|`、重复的小标题在一份文档里出现多次,`find()` 找到的是别处那一次。
#
# 两版栽在同一件事上:**我以为某个东西唯一,而它不唯一。**
# 现在用解析时记下的**原文起始行号** —— 那个才真唯一。
# (它会随文档编辑而漂,所以**只给检查用**,对外引用仍然是「节路径 + 段序号」。)
按起始行 = {}
for f in 文件们:
    原 = open(os.path.join(语料目录, f), encoding="utf-8").read()
    解 = P.解析(原, 文件名=f)
    按起始行[f] = {b["位置"]["起始行"]: b["位置"]["节路径"] for b in 解["块们"]}

跨节 = []
for f in 文件们:
    原 = open(os.path.join(语料目录, f), encoding="utf-8").read()
    r = C.切(P.解析(原, 文件名=f), 文档版本id=f"dv_{f}")
    for c in r["片段们"]:
        if c["合并了几段"] <= 1:
            continue
        节们 = {按起始行[f].get(行) for 行 in c["_原文起始行们"]}
        if 节们 != {c["section_path"]}:
            跨节.append((f, c["section_path"][-20:], sorted(x[-16:] for x in 节们 if x)))

合并过的 = sum(1 for f in 文件们
              for c in C.切(P.解析(open(os.path.join(语料目录, f), encoding="utf-8").read(),
                                  文件名=f), 文档版本id="x")["片段们"]
              if c["合并了几段"] > 1)
ck("合并过的片段,它的每一段都属于它自己那一节", not 跨节, 合并过的, 跨节[:2])
ck("**真的有片段被合并过**(一个从不合并的切片器也能通过上一条)",
   合并过的 > 0, 合并过的)

print("\n▸ ③ ordinal / text_hash / 版本号")
for f in 文件们[:1]:
    原 = open(os.path.join(语料目录, f), encoding="utf-8").read()
    r = C.切(P.解析(原, 文件名=f), 文档版本id="dv_a")
    片 = r["片段们"]
    ck("ordinal 从 1 连续编,没断号(index_members 要靠它对上)",
       [c["ordinal"] for c in 片] == list(range(1, len(片) + 1)), len(片))
    ck("每个片段都有 text_hash(认出「同一段内容」靠它,不靠 ordinal)",
       all(c["text_hash"].startswith("sha256:") for c in 片), len(片))
    ck("**每个片段都绑了文档版本 id**(绑文档的话,文档一改历史证据链就指向新内容)",
       all(c["文档版本id"] == "dv_a" for c in 片), len(片))
    ck("解析器版本和切片器版本都带出来了"
       "(升级任一个都会改变切片结果,而两个索引就不可比了)",
       r["解析器版本"] and r["切片器版本"], 2,
       f"{r['解析器版本']} / {r['切片器版本']}")
    # 同一份内容切两次,哈希必须一样 —— 否则「这份资料变没变」判不了
    r2 = C.切(P.解析(原, 文件名=f), 文档版本id="dv_a")
    ck("**同一份原文切两次,每个片段的哈希一样**(否则「资料变没变」判不了)",
       [c["text_hash"] for c in r["片段们"]] == [c["text_hash"] for c in r2["片段们"]],
       len(片))

print("\n▸ ④ 认不出的格式当场报,不假装解析成功")
def _抛(f, 类):
    try: f(); return False
    except 类: return True
    except Exception: return False
ck("**PDF / 扫描件不假装解析**(把 PDF 读成乱码,产出的片段形状和正常的一样)",
   _抛(lambda: P.解析("%PDF-1.4 ...", 文件名="a.pdf"), P.解析不了), 1)
NL = chr(10)
ck("空文档不被静默索引成 0 个片段",
   _抛(lambda: P.解析("   " + NL + NL + "  ", 文件名="a.md"), P.解析不了), 1)
ck("只有分隔符的文档 → 报「解析失败」,不报「文档是空的」",
   _抛(lambda: P.解析("---" + NL + NL + "***" + NL, 文件名="a.md"), P.解析不了), 1)
ck("**没绑文档版本 id 不许切**(一条不知道自己属于哪一版的片段是断掉的证据链)",
   _抛(lambda: C.切(P.解析("# a" + NL + NL + "正文够长的一段话在这里放着当样本用途明确",
                         文件名="a.md"), 文档版本id=None), ValueError), 1)

print("\n▸ ⑤ 丢掉的块要报出来,不静默")
r = P.解析(NL.join(["# 标", "", "第一段够长够长够长够长够长够长", "",
                   "---", "", "第二段也够长够长够长够长", ""]), 文件名="a.md")
ck("分隔符块被丢掉,**而且计入「丢了几块」并进警告**"
   "(只报「切出 N 块」的话,某天正文被当分隔符丢掉没人看得出来)",
   r["丢掉的块数"] == 1 and any("分隔符" in w for w in r["警告"]), 2,
   f"丢 {r['丢掉的块数']} · {r['警告']}")

print("\n▸ ⑥ token 数是**粗估**,不许当实测")
ck("token_count 只是粗估(真实 token 要问 tokenizer,而各模型不一样)——"
   "**不许拿它算钱**",
   "粗估" in (C._粗估token.__doc__ or "") and "不许拿它去算钱" in (C._粗估token.__doc__ or ""),
   1)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
