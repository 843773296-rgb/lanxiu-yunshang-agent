#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""答案缓存键的纯逻辑 —— **零 IO,跑在 CI 里**。

缓存规格附录 A-2 的「怎么验证的」栏点名了三件,这一份就是那三件:

> 「**对照字段单独变动必须改变键**,**等价对象键顺序不变键**;**独立期望值验证**。」

## 为什么第一条要**逐个字段**跑,不是抽几个

键里有 17 个必填字段。漏登一个的后果是**那个维度上的答案会被错用** ——
比如漏了 `authorization_epoch`,撤权之后旧答案照样命中。

而漏登在代码里**看不出来**:字段表是一个元组,少一项和多一项长得一样。
所以这里按 `必填` 这个元组**逐项**改一个值、断键必须变 ——
> **一条只抽查了三个字段的判据,和一条全验了的,在绿勾上长得一模一样。**

## 「独立期望值」在这里是什么意思

A-2 要求独立期望值。对哈希来说,「独立」不是再写一遍 HMAC(那是同源谬误)——
而是**用性质**:同输入同键、改一处必变、换对象键顺序不变、换密钥必变。
这些性质不依赖我们怎么实现它。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "cache"))

import key_builder as K

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


密 = b"0123456789abcdef0123456789abcdef"       # 自测用,不是真密钥
另一把 = b"fedcba9876543210fedcba9876543210"

# 一份齐全的字段。**每个值都长得不一样**,这样「两个字段被写串了」也验得出来。
齐 = {
    "key_schema_version": K.键结构版本,
    "project_id": "proj_A", "environment": "test",
    "application_id": "app_A", "release_manifest_id": "rel_1",
    "cache_policy_version": "cpv_1", "namespace_generation": 7,
    "principal_or_verified_scope": "user_甲", "authorization_epoch": 3,
    "input_payload_hash": "sha256:aaa",
    "knowledge_manifest_revision": "km_11",
    "retrieval_pipeline_revision": "rp_2",
    "model_connection_revision": "mc_5",
    "model_resolved_revision": "claude-haiku-4-5",
    "generation_parameters": {"temperature": 0, "max_tokens": 1024},
    "output_schema_revision": "os_1", "locale": "zh-CN",
}
理由 = {"relevant_conversation_hash": "这是无会话的只读任务",
       "memory_revision": "这个任务不读记忆"}

print("答案缓存键(规格 §10.1 / 附录 A-2)")
print("=" * 92)

print("\n▸ ① 同输入 → 同键(确定性)")
k1, 料1 = K.算键(齐, 密钥=密, 不需要的理由=理由)
k2, _ = K.算键(dict(齐), 密钥=密, 不需要的理由=理由)
ck("同一份字段算两次,键一样", k1 == k2, k1[:16])
ck("键是 64 位十六进制(HMAC-SHA256)", len(k1) == 64 and all(
    c in "0123456789abcdef" for c in k1), len(k1))
ck("**规范化后的串里没有密钥**(它要给「技术详情」看)",
   "0123456789abcdef" not in 料1, 料1[:80])

print("\n▸ ② **逐个必填字段**改一个值 → 键必须变(A-2 点名的那条)")
变了, 没变 = [], []
for 字段名 in K.必填:
    if 字段名 == "key_schema_version":
        continue                     # 它改了会抛,下面单独验
    改 = dict(齐)
    v = 改[字段名]
    改[字段名] = (v + 1) if isinstance(v, int) and not isinstance(v, bool) else (
        {**v, "temperature": 1} if isinstance(v, dict) else str(v) + "_x")
    kx, _ = K.算键(改, 密钥=密, 不需要的理由=理由)
    (变了 if kx != k1 else 没变).append(字段名)
ck(f"**{len(变了)} 个字段逐个单独改动,每一个都让键变了**(没变的:{没变 or '无'})",
   not 没变, 没变)
ck("而且真的逐项跑过(**不是抽查**)—— 验了多少个要报出来",
   len(变了) == len(K.必填) - 1, f"{len(变了)}/{len(K.必填) - 1}")

print("\n▸ ③ 等价对象 → 同键;而数组换序 → **不同键**")
换序 = dict(齐, generation_parameters={"max_tokens": 1024, "temperature": 0})
k换, _ = K.算键(换序, 密钥=密, 不需要的理由=理由)
ck("对象的**键顺序**换了 → 键不变(对象的键没有语义顺序)", k换 == k1)
数组A = dict(齐, input_payload_hash=["片段1", "片段2"])
数组B = dict(齐, input_payload_hash=["片段2", "片段1"])
kA, _ = K.算键(数组A, 密钥=密, 不需要的理由=理由)
kB, _ = K.算键(数组B, 密钥=密, 不需要的理由=理由)
ck("数组**换序 → 键要变** —— 检索结果的顺序会改变答案,"
   "排序数组会让两种顺序撞在一起", kA != kB, (kA[:12], kB[:12]))

print("\n▸ ④ `None` / `\"\"` / `0` / `False` **互不相同**(第 ② 条硬规矩)")
形状 = {}
for 名, 值 in (("None", None), ("空串", ""), ("零", 0), ("假", False),
             ("零点零", 0.0), ("字符串零", "0")):
    形状[名] = K.规范化({"x": 值})
ck("六种「空/零」折出来**两两不同** —— "
   "「没有会话」和「会话是空串」是两件事,撞了就会跨任务复用",
   len(set(形状.values())) == 6,
   {k: v for k, v in list(形状.items())[:3]})

print("\n▸ ⑤ 文本**一个字都不许动**(规格:不自动删空白、不归一化数字)")
对 = [("不含", "不 含"), ("3 天", "3.0 天"), ("藏青", "藏靑"),
     ("abc", "ABC"), ("x", "x ")]
串 = [(a, b) for a, b in 对 if K.规范化({"q": a}) == K.规范化({"q": b})]
ck("这几对**各自算出不同的键**(删空白会让「不含」和「不 含」撞;"
   "归一化数字会让工期差一天的两个答案撞)", not 串, 串)

print("\n▸ ⑥ 缺字段 → **抛**,绝不拿空串顶(这一份最要紧的一条)")
for 字段名 in ("project_id", "authorization_epoch", "model_resolved_revision"):
    缺 = {k: v for k, v in 齐.items() if k != 字段名}
    try:
        K.算键(缺, 密钥=密, 不需要的理由=理由)
        ck(f"缺 `{字段名}` → 抛", False, "**它没抛 —— 等于用空串顶了**")
    except K.算不出键 as e:
        ck(f"缺 `{字段名}` → 抛,而且点名了那个字段", 字段名 in str(e), str(e)[:90])
给了None = dict(齐, release_manifest_id=None)
try:
    K.算键(给了None, 密钥=密, 不需要的理由=理由)
    ck("必填字段给 `None` → 抛", False, "它没抛")
except K.算不出键 as e:
    ck("必填字段给 `None` → 抛(「拿不到」要抛,由上层决定绕过)",
       "None" in str(e) or "绕过" in str(e), str(e)[:90])

print("\n▸ ⑦ 可选字段:**要么给值,要么给理由**(规格 §10.1)")
try:
    K.算键(齐, 密钥=密, 不需要的理由={"relevant_conversation_hash": "无会话"})
    ck("少写一个「不需要的理由」→ 抛", False, "它没抛")
except K.算不出键 as e:
    ck("`memory_revision` 既没给值也没写理由 → **抛**(静默缺席 ≠ 想清楚了不需要)",
       "memory_revision" in str(e), str(e)[:100])
k有会话, _ = K.算键(dict(齐, relevant_conversation_hash="conv_1",
                      memory_revision="mem_2"), 密钥=密,
                 不需要的理由={})
ck("给了会话和记忆版本 → 键和「无会话」那次**不同**", k有会话 != k1)
try:
    K.算键(齐, 密钥=密, 不需要的理由={**理由, "project_id": "我不需要项目"})
    ck("拿「理由」去豁免一个必填字段 → 抛", False, "它没抛")
except K.算不出键 as e:
    ck("**必填字段不许用理由豁免掉**", "project_id" in str(e), str(e)[:90])

print("\n▸ ⑧ 密钥:换一把 → 键变;弱密钥 → 抛;而**异常里不回显密钥**")
k另, _ = K.算键(齐, 密钥=另一把, 不需要的理由=理由)
ck("换一把密钥 → 键变(密钥代次换了就是新命名空间)", k另 != k1)
for 坏, 叫法 in ((b"short", "太短"), ("是个字符串", "不是 bytes"), (None, "None")):
    try:
        K.算键(齐, 密钥=坏, 不需要的理由=理由)
        ck(f"密钥{叫法} → 抛", False, "它没抛")
    except K.算不出键 as e:
        ck(f"密钥{叫法} → 抛,**而异常里不出现密钥内容**",
           "short" not in str(e) and "字符串" not in str(e).replace("要 bytes", ""),
           str(e)[:70])

print("\n▸ ⑨ 键结构版本对不上 → **不混算**")
try:
    K.算键(dict(齐, key_schema_version="ak0"), 密钥=密, 不需要的理由=理由)
    ck("版本对不上 → 抛", False, "它没抛")
except K.算不出键 as e:
    ck("版本对不上 → 抛 —— 两套字段表算出的键落在同一命名空间里,"
       "而「版本不同」在哈希上看不出来", "ak0" in str(e), str(e)[:90])

print("\n▸ ⑩ 认不出的类型 → **抛,不猜怎么序列化**")
try:
    K.规范化({"x": {1, 2}})          # set:没有确定顺序
    ck("`set` → 抛(它没有确定顺序,序列化出来每次可能不一样)", False, "它没抛")
except K.算不出键 as e:
    ck("`set` → 抛(它没有确定顺序,**而一个不确定的键等于没有键**)",
       "认不出的类型" in str(e), str(e)[:80])

print("\n▸ ⑪ `查字段` 能在**算键之前**把缺什么说清(给页面用)")
问 = K.查字段({k: v for k, v in 齐.items() if k not in
            ("project_id", "locale")}, 不需要的理由=理由)
ck("两个字段都缺 → 报出来,而且**两个都点名**(不是只报第一个)",
   问 and "project_id" in str(问) and "locale" in str(问), str(问)[:120])
ck("齐了就不报", K.查字段(齐, 不需要的理由=理由) == [])

print("\n" + "=" * 92)
print(f"{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
for x in 挂:
    print("   挂:", x)
sys.exit(1 if 挂 else 0)
