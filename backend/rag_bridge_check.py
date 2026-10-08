#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat 接管理后台 RAG 这条桥 —— **零 IO,不调模型、不发请求**。

业务 2026-10-08 拍的第 ④ 步接上之后,这条桥上有三件**坏了不报错**的事:

   ① **退路悄悄长回来** —— 有人看到 `kb_rag` 返回 error 之后答得难看,
      顺手加一句「查不了就用 kb_read 兜一下」。
      > 一次「知识库查不了」和一次「它根本没查」,
      > **在顾问看到的那段回答上长得一模一样。**
   ② **岗位→角色的映射被改大** —— 今天两级 ACL 全是空的,
      改成 `admin` 一样跑得通、一样看不出来;
      而 ACL 真填上那天,顾问就拿着管理员的语料权限在查。
   ③ **管它的那条规矩(TL64)被删或被改软** —— 工具还在、规矩没了,
      而 P6 只验「挂了工具有没有规矩」,**不验规矩里那几句还在不在**。

这一份盯这三件。它**不碰库、不发请求**,所以进根门禁。
"""
import io
import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "backend"))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


api源 = io.open(os.path.join(根, "backend", "api.py"), encoding="utf-8").read()
# 只取 kb_rag 那一段(整文件太大,别处有别的东西)
起 = api源.index("def kb_rag(")
那一段 = api源[起:api源.index("\nTOOLS.update(", 起)]
提示源 = io.open(os.path.join(根, "prompts.py"), encoding="utf-8").read()

print("\n\033[1m▸ chat 接管理后台 RAG 这条桥(零 IO)\033[0m")
print("=" * 76)

print("\n① 这条路断了就说出来,**不退回别的工具**(业务 2026-10-08 拍)")
# ⚠️ 判据查的是**返回值的形状**:每条失败出口都要带 `error` + `怎么办`。
# ⚠️ **不要用 `[^}]*` 去切 return 块。** 第一版这么写,而失败出口里有
# f-string(`f"连不上管理后台({_后台基址}):…"`)—— 正则**在那个花括号上就停了**,
# 于是 `怎么办` 还没被扫到就被判成「没带」。
# > 一条「判据发现了真问题」的红,和一条「判据自己切错了范围」的红,
# > **在那个 ❌ 上长得一模一样** —— 而我照着它去改代码,会把对的改坏。
# 改成:从每个 `return {"error"` 起,切到**下一个 return / def 之前**。
def _出口们(文):
    出 = []
    for m in re.finditer(r'return \{"error"', 文):
        尾 = 文[m.start() + 10:]
        切 = min([x for x in (尾.find("\n    return "), 尾.find("\ndef "),
                             len(尾)) if x > 0] or [len(尾)])
        出.append(文[m.start():m.start() + 10 + 切])
    return 出


出口们 = _出口们(那一段)
ck(f"失败出口都带 `error`(找到 {len(出口们)} 条)", len(出口们) >= 4, len(出口们))
ck("每条失败出口都带**怎么办**(只说坏了不说怎么办,人只能去猜)",
   all("怎么办" in x for x in 出口们),
   [x[:40] for x in 出口们 if "怎么办" not in x][:1] or "都带了")
ck("🔑 连不上时的建议是「照实说查不了,别凭记忆答」—— **不是「换个工具」**",
   "别凭记忆答" in 那一段 and "换个工具" not in 那一段)
ck("↳ 而且 `hit=0`(检索跑成了但没选中)**和「查不了」分开** —— "
   "前者是真的「知识库里没有」",
   '"hit": 0' in 那一段 and "和「查不了」不是一回事" in 那一段)
ck("显式传 `要生成: False` —— 只拿证据,让 chat 自己的模型照着答"
   "(两个模型答同一个问题,转述那一步会悄悄改意思)",
   '"要生成": False' in 那一段)

print("\n② 岗位→角色的映射:**不许悄悄改大**")
import api  # noqa: E402  —— 读常量,不跑任何工具
表 = api.岗位到后台角色
ck("映射表是显式的常量(不是现算的)", isinstance(表, dict) and len(表) >= 3, 表)
ck("🔑 **一个 admin 都没有** —— 今天 ACL 全空,改成 admin 一样跑得通、"
   "一样看不出来;而 ACL 填上那天顾问就拿着管理员权限在查",
   "admin" not in set(表.values()), sorted(set(表.values())))
ck("↳ 也没有 approver / trainer 这类带写权限语义的角色",
   not ({"approver", "trainer", "editor"} & set(表.values())),
   sorted(set(表.values())))
ck("源码里写明**这张表业务还没拍**(拍了要改这里)",
   "业务还没拍" in 那一段 or "业务还没拍" in api源[:起])
ck("岗位没登记时**拒**,不挑一个默认角色顶上"
   "(顶上的那个可能比它该有的权限大,而那件事不报错)",
   "不认识这个岗位" in 那一段)

print("\n③ 管它的规矩(TL64)—— **工具还在、规矩被改软**也要红")
ck("TL64 在,而且 `needs` 正是 `kb_rag`",
   re.search(r'Rule\("TL64",\s*\("kb_rag",\)', 提示源) is not None)
for 这句, 为什么 in (
    ("照实说「知识库现在查不了」", "拍板①:断了就要说出来"),
    ("不许换个工具再查一遍", "否则模型会把话用自己的知识圆回来"),
    ("出处要带给顾问", "一个查不回去的引用比没有引用糟"),
    ("只能在 `kb_rag` 真的返回 hit=0 之后说", "实测撞到过:它看着不像自己的范围就不查了"),
    ("判断「是不是我的范围」要在查过之后", "同上,这是那次的修法"),
):
    ck(f"TL64 里还写着「{这句[:18]}…」({为什么})", 这句 in 提示源)

print("\n④ 工具说明(给模型看的那段)")
规格 = [t for t in api.KB_SCHEMAS if t["name"] == "kb_rag"]
ck("kb_rag 登记进了 KB_SCHEMAS(没登记模型就看不见它)", len(规格) == 1)
if 规格:
    d = 规格[0]
    ck("🔑 schema 的属性名**都是 ASCII** —— 中文属性名会被 API 当场拒"
       "(这个项目第四次踩中文标识符)",
       all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k)
           for k in d["input_schema"]["properties"]),
       list(d["input_schema"]["properties"]))
    ck("说明里讲清了和 `kb_read` 的分工(不然模型两个混着用)",
       "kb_read" in d["description"])
    ck("说明里也讲了 error 和 hit=0 是两回事",
       "error" in d["description"] and "hit=0" in d["description"])

print()
if 挂:
    print(f"  {R}❌ {len(挂)} 条挂了{D}")
    for x in 挂:
        print(f"     · {x}")
    sys.exit(1)
print(f"  {G}✅ {len(过)} 条全过{D}")
print("  ⚠️ 盲区:它验的是**这条桥的形状**,不验「模型真的会调它」——")
print("     后者要真跑(2026-10-08 实测:问「几星算差评」走 kb_read→kb_rag,")
print("     而问「评价进不进考核」第一次一个工具都没调,是补了 TL64 第五条才对的)。")
