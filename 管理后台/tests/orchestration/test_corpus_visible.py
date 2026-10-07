#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**这段语料这个人能不能检索到** —— 零 IO。规格 §18「文档父级权限可收紧」。

## 这一组每一条都对着一种**悄悄放开**的方式

   ① 空 ACL 读成「谁都看不见」或「谁都能看」—— 两种读法后果相反
   ② 文档能放宽(子集检查漏了)→ 一篇文档就能绕开知识库那一级
   ③ 认不出的角色名忽略掉 → 一个拼错的角色静静消失,而 ACL 看起来仍填着东西
   ④ 没有角色时兜一个「看全部」→ 未登录的人读到全部语料
   ⑤ **where 片段和纯判定给出不同的名单** —— 两份各自的测试都绿,而名单不一样

## ⚠️ 第 ⑤ 节是这一组存在的主要理由

检索那头不可能把一万条切片捞出来逐条判,所以它写 SQL;
而「这篇文档这个人能不能看」那头调纯判定。**同一套口径,两种表示。**
> 一份 SQL 过滤和一份纯判定,**在各自的测试里都绿** —— 而它们可以给出不同的名单。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "contract"))

import 语料可见 as V
import perms as PM

G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = 0, 0


def _试抛(名):
    """传 `名` 当角色,该抛 `判不了`。返回真/假给 ck。"""
    try:
        V.看得到吗(这个人的角色们=[名], 知识库acl=None)
    except V.判不了:
        return True
    return False


def _不抛(名):
    try:
        V.看得到吗(这个人的角色们=[名], 知识库acl=None)
        return True
    except V.判不了:
        return False


def ck(说, ok, 附=""):
    global 过, 挂
    if ok:
        过 += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        挂 += 1
        print(f"  {R}❌{D} {说}  {附}")


看 = lambda **kw: V.看得到吗(**kw)[0]

print("▸ ① 角色字面量只有一份(两套枚举迟早分叉,而分叉时两边各自都是绿的)")
ck("角色来自 contract/perms,不是自己造的", V.角色们 == tuple(PM.角色们), V.角色们)
ck("六种角色都在", len(V.角色们) == 6, len(V.角色们))

print("\n▸ ② 🔑 只能收紧,不能放宽(规格 §18)")
ck("库 {editor,admin} → 文档 {admin} 是收紧",
   V.定(知识库acl=["editor", "admin"], 文档acl=["admin"])[0] == {"admin"})
try:
    V.定(知识库acl=["admin"], 文档acl=["editor", "admin"])
    ck("文档想放宽 → 拒", False, "它没拒")
except V.判不了 as e:
    ck("🔑 文档想放宽 → **拒**", "不可放宽" in str(e))
    ck("而且说清**被哪一级卡住**", "知识库这一级" in str(e))
    ck("还说清**多出来的是谁**", "editor" in str(e) and "多出来" in str(e))
    ck("并给出下一步(去改知识库那一级)", "先改知识库" in str(e))
# 两级相同不算放宽
ck("两级完全一样 → 不算放宽",
   V.定(知识库acl=["admin"], 文档acl=["admin"])[0] == {"admin"})

print("\n▸ ③ 🔑 空 ACL 是「没说过」,不是「没有人」")
# > 一份「空 = 全部可见」的系统,和一份「空 = 谁都看不见」的,
# > **在那个 NULL 上长得一模一样** —— 前者默认开放,后者默认关闭。
ck("两级都空 → 全部角色(上限不能是空集)",
   V.定()[0] == set(V.角色们), sorted(V.定()[0]))
ck("文档空 → 继承知识库", V.定(知识库acl=["admin"])[0] == {"admin"})
ck("理由里说清是「继承上一级」", "继承上一级" in V.定(知识库acl=["admin"])[1])
# ⚠️ 空列表和 None 一样对待 —— 「前端传了空数组」比「故意谁都不许看」常见得多
for 空 in (None, [], {}, {"roles": None}, {"roles": []}):
    ck(f"文档 ACL 是 {空!r} → 当「没说过」,不是「谁都看不见」",
       V.定(知识库acl=["admin"], 文档acl=空)[0] == {"admin"})

print("\n▸ ④ 认不出的角色 / 没有角色 —— 都当场抛,**不兜底成可见**")
for 坏 in (["admin", "店长"], ["ADMIN"], [""], ["admin "]):
    try:
        V.定(知识库acl=坏)
        ck(f"{坏!r} → 抛", False, "它没抛")
    except V.判不了 as e:
        ck(f"认不出的角色 {坏!r} → **抛**(不忽略)", "不忽略" in str(e) or "不是认得的角色" in str(e))
try:
    V.看得到吗(这个人的角色们=None)
    ck("不知道他有哪些角色 → 抛", False, "它没抛")
except V.判不了 as e:
    ck("🔑 不知道他有哪些角色 → **抛**(判不了不等于可见)", "判不了不等于可见" in str(e))
try:
    V.where片段(这个人的角色们=[])
    ck("没有角色时要 where 片段 → 抛", False, "它没抛")
except V.判不了 as e:
    ck("🔑 没有角色 → **不给「看全部」的兜底**", "不给一个「看全部」的兜底" in str(e))

print("\n▸ ⑤ 看得到吗:逐例")
ck("admin 看 {admin} 的文档 → 看得到",
   看(这个人的角色们=["admin"], 知识库acl=["editor", "admin"], 文档acl=["admin"]))
ck("editor 看 {admin} 的文档 → 看不到",
   not 看(这个人的角色们=["editor"], 知识库acl=["editor", "admin"], 文档acl=["admin"]))
ck("一人多角色,命中一个就够",
   看(这个人的角色们=["viewer", "admin"], 知识库acl=["admin"]))
ck("看不到时说清**你的角色**和**可见范围**各是什么",
   all(x in V.看得到吗(这个人的角色们=["editor"], 文档acl=["admin"])[1]
       for x in ("editor", "admin")))

print("\n▸ ⑥ 🔑 where 片段和纯判定**给出同一份名单**")
# 不起库:用 Python 照 SQL 的语义算一遍(coalesce + ?| 任一键存在),
# 和纯判定逐例比。**两种表示必须对得上。**
def 按sql语义(我的角色们, 库acl, 文acl):
    片段, 参 = V.where片段(这个人的角色们=我的角色们)
    # coalesce(文档, 知识库):jsonb 里 None/缺键当 null
    取 = lambda a: (a.get("roles") if isinstance(a, dict) else a) or None
    有效 = 取(文acl) if 取(文acl) is not None else 取(库acl)
    if 有效 is None:
        return True                      # `is null` 那一支 → 全部可见
    return bool(set(有效) & set(参["角色们"]))   # `?|` 任一命中

组合 = [(我, 库, 文)
       for 我 in (["admin"], ["editor"], ["viewer", "editor"], ["trainer"])
       for 库 in (None, ["admin"], ["editor", "admin"], ["viewer", "editor", "admin"])
       for 文 in (None, [], ["admin"], ["editor"], ["editor", "admin"])]
比了, 不符 = 0, []
for 我, 库, 文 in 组合:
    try:
        纯 = 看(这个人的角色们=我, 知识库acl=库, 文档acl=文)
    except V.判不了:
        continue                         # 放宽那种本来就该拒,SQL 侧不负责拦
    比了 += 1
    if 按sql语义(我, 库, 文) != 纯:
        不符.append((我, 库, 文, 纯))
ck(f"两种表示在 {比了} 个组合上给出同一个答案", not 不符, 不符[:3])
ck("对账样本不是空的(**空集合上两边永远一致**)", 比了 >= 40, 比了)
# 🔑 对照组:把 SQL 侧故意算错一种,确认这条对账抓得到
坏的 = [(我, 库, 文) for 我, 库, 文 in 组合
       if 库 == ["admin"] and 文 is None and 我 == ["editor"]]
ck("🔑 对照:editor 在「库限 admin、文档没说过」时**两边都该是看不到**",
   坏的 and not 看(这个人的角色们=["editor"], 知识库acl=["admin"])
   and not 按sql语义(["editor"], ["admin"], None))

print("\n▸ ⑥.5 **角色 ≠ 专项授权** —— 传错一个就打开一把万能钥匙")
# `perms.判(能力, 角色, 专项)`:一个人只有一个角色,`专项`(身份.grants)是
# **能力级**授权。接的人很容易写 `[me.role] + me.grants`,而那一行让专项授权
# 成了绕过语料 ACL 的路子。
# ⚠️ 能力名**从 PM 现读,不手抄** —— 手抄的话能力改名后这条照旧绿,
#    而「它还在验」和「它在验一个不存在的名字」长得一模一样。
一条能力 = sorted(PM.能力们)[0]
ck(f"拿一条真能力名(`{一条能力}`)当角色传 → 当场抛,不静静忽略",
   _试抛(一条能力), 一条能力)
真角色 = sorted(set(PM.角色们))[0]
ck(f"🔑 对照:真角色名(`{真角色}`)传进去不抛",
   _不抛(真角色), 真角色)
ck("能力名和角色名**没有一个重名** —— 重名的话上面那条判据就失效了,"
   "而它仍然会绿",
   not (set(PM.能力们) & set(PM.角色们)),
   sorted(set(PM.能力们) & set(PM.角色们)))

print("\n▸ ⑦ 切片级:业务 2026-10-07 拍了不做")
ck("这个模块不提供切片级判定(要收紧就拆成独立文档)",
   not any("切片" in n for n in dir(V) if not n.startswith("_")),
   [n for n in dir(V) if not n.startswith("_")])
ck("而文档里写清了为什么(切片是派生物,重建就整批重切)",
   "派生物" in (V.__doc__ or ""))
ck("也写清了这是**召回层**的权限,不假装解决了推理层",
   "推理层" in (V.__doc__ or "") or "召回层" in (V.__doc__ or ""))

print("\n" + "=" * 92)
if 挂:
    print(f"{R}❌ 过 {过} / 挂 {挂}{D}")
    sys.exit(1)
print(f"{G}✅ 过 {过} / 挂 {挂}{D}")
