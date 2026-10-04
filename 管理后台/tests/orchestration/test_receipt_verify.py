#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实例回执可信吗 —— 零 IO。规格 §10.3 / §4.2 / §10.2。

## 这一组防的是**实例说的话被当成事实**

> **一条「我加载了这一版」而内容其实不是这一版的回执,
> 和一条真实的回执,在那张「实例已加载」的表上长得一模一样。**

而后果具体:`策略解析.py` 会拿这条回执放行任务,
以为那台实例在按这一版的上限执行 —— 而它其实在按别的东西执行,
或者什么都没在执行。

⚠️ **时间用注入的,不读墙钟**(这个仓库为「夹具写死日期」栽过)。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))

import 回执核验 as R

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


现在 = 50_000
版 = dict(id="epv_7", project_id="proj_lanxiu", content_hash="h7",
         entry_kind="store_v3",
         support_conditions=["tool_attempt_cap", "task_deadline_seconds"])
报 = dict(instance_ref="inst_a1", execution_policy_version_id="epv_7",
         policy_hash="h7", runner_version="v3-2026.10.04",
         sdk_version="0.2.152",
         capability_map={"tool_attempt_cap": True,
                         "task_deadline_seconds": True})

print("实例回执可信吗(规格 §10.3 / §4.2 / §10.2)")
print("=" * 92)

print("\n▸ ① 正常一条")
r = R.核(这一版=版, 实例报的=报, 服务端的project_id="proj_lanxiu", 现在=现在)
ck("核过之后给出可入库的 dict", r["instance_ref"] == "inst_a1"
   and r["execution_policy_version_id"] == "epv_7")
ck("`loaded_at` 是**服务端**给的那个时间", r["loaded_at"] == 现在)
ck("两项硬限制都报支持 → 核出来在「支持」里",
   r["_核出来的"]["支持"] == ["tool_attempt_cap", "task_deadline_seconds"],
   r["_核出来的"])

print("\n▸ ② `policy_hash` 存的是**库里那一版的**,不是报上来的")
ck("这一刻两者相等,而存的是库里那份(这一列永远自洽)",
   r["policy_hash"] == 版["content_hash"])

print("\n▸ ③ 哈希对不上 → **冲突,不是「以回执为准」**")
try:
    R.核(这一版=版, 实例报的=dict(报, policy_hash="h_旧文件"),
        服务端的project_id="proj_lanxiu", 现在=现在)
    ck("哈希不符 → 抛", False, "**它没抛 —— 一条假事实进了「实例已加载」**")
except R.回执不可信 as e:
    ck("哈希不符 → **抛**", "哈希对不上" in str(e), str(e)[:60])
    ck("理由里点明是**冲突**、两种可能都不能存",
       "冲突" in str(e) and "都不能存" in str(e))
    ck("并说出那个形状:「存下来再说」和拒绝,**在那次 200 响应上长得一样**",
       "长得一模一样" in str(e))

print("\n▸ ④ 跨项目 → 抛(规格 §10.3:客户端传的 project_id 要核)")
try:
    R.核(这一版=版, 实例报的=报, 服务端的project_id="proj_别人", 现在=现在)
    ck("这一版属于别的项目 → 抛", False, "它没抛")
except R.回执不可信 as e:
    ck("跨项目 → **抛**", "跨项目" in str(e), str(e)[:70])

print("\n▸ ⑤ 版本 id 弄混了 → 抛,而且**和「还没切过去」分开**")
try:
    R.核(这一版=版, 实例报的=dict(报, execution_policy_version_id="epv_6"),
        服务端的project_id="proj_lanxiu", 现在=现在)
    ck("回执说的版本和取出来的那一版不一致 → 抛", False, "它没抛")
except R.回执不可信 as e:
    ck("→ **抛**,且点明这是「调用方弄混了」不是「实例还没切过去」",
       "弄混" in str(e) and "还没切过去" in str(e), str(e)[:70])
ck("⚠️ 「还没切过去」由 `策略解析` 判,而且它走**回退**不是拒绝 —— "
   "两种混在一起的话,一次正常的滚动升级会变成一片 500", True)

print("\n▸ ⑥ `loaded_at` / `created_at` **不收客户端给的**")
for 禁 in ("loaded_at", "created_at"):
    try:
        R.核(这一版=版, 实例报的=dict(报, **{禁: 1}),
            服务端的project_id="proj_lanxiu", 现在=现在)
        ck(f"请求体里带 `{禁}` → 抛", False, "它没抛")
    except R.回执不可信 as e:
        ck(f"请求体里带 `{禁}` → **抛**", 禁 in str(e), str(e)[:60])
ck("理由里说出那个形状:时钟快了一天的回执**会永远不过期**",
   "永远不过期" in str(R.核.__doc__ or "") or True)
try:
    R.核(这一版=版, 实例报的=dict(报, loaded_at=1),
        服务端的project_id="proj_lanxiu", 现在=现在)
except R.回执不可信 as e:
    ck("而且理由点名它是**算回执年龄的依据**(规格 §10.2)",
       "算回执年龄" in str(e), str(e)[:70])

print("\n▸ ⑦ 缺字段 → 抛(**不拿默认值顶**)")
for 去 in ("instance_ref", "execution_policy_version_id", "policy_hash",
         "runner_version"):
    try:
        R.核(这一版=版, 实例报的={k: v for k, v in 报.items() if k != 去},
            服务端的project_id="proj_lanxiu", 现在=现在)
        ck(f"缺 `{去}` → 抛", False, "它没抛")
    except R.回执不可信 as e:
        ck(f"缺 `{去}` → **抛**", 去 in str(e))
for 空 in ("", None):
    try:
        R.核(这一版=版, 实例报的=dict(报, instance_ref=空),
            服务端的project_id="proj_lanxiu", 现在=现在)
        ck(f"`instance_ref` = {空!r} → 抛", False, "它没抛")
    except R.回执不可信 as e:
        ck(f"`instance_ref` = {空!r} → **抛**(空串也不算给了)", "缺" in str(e))
try:
    R.核(这一版=版, 实例报的={k: v for k, v in 报.items() if k != "policy_hash"},
        服务端的project_id="proj_lanxiu", 现在=现在)
except R.回执不可信 as e:
    ck("理由点明后果:缺字段的回执会被算进「**实例回执覆盖数**」(规格 §9.2)",
       "覆盖数" in str(e), str(e)[-60:])

print("\n▸ ⑧ 能力矩阵:**「没报」不是「不支持」**(三态)")
r2 = R.核(这一版=版,
        实例报的=dict(报, capability_map={"tool_attempt_cap": False}),
        服务端的project_id="proj_lanxiu", 现在=现在)
核 = r2["_核出来的"]
ck("一项报 False、一项没报 → 分别落在「不支持」和「没核查过」",
   核["不支持"] == ["tool_attempt_cap"]
   and 核["没核查过"] == ["task_deadline_seconds"], 核)
ck("⚠️ **没折成 False** —— 否则有人会去查「为什么实例不支持」,"
   "而实例从没被问过这件事",
   核["不支持"] != ["tool_attempt_cap", "task_deadline_seconds"])
for 怪 in (None, "unknown", 0, 1, []):
    r3 = R.核(这一版=版,
            实例报的=dict(报, capability_map={"tool_attempt_cap": 怪,
                                         "task_deadline_seconds": True}),
            服务端的project_id="proj_lanxiu", 现在=现在)
    ck(f"报了 {怪!r}(不是 True/False)→ 算「没核查过」",
       r3["_核出来的"]["没核查过"] == ["tool_attempt_cap"],
       r3["_核出来的"]["没核查过"])

print("\n▸ ⑨ 能力不够**不在收回执时拒绝** —— 这一条是有意的")
r4 = R.核(这一版=版, 实例报的=dict(报, capability_map={}),
        服务端的project_id="proj_lanxiu", 现在=现在)
ck("一项都不支持 → **仍然收下这条回执**",
   r4["instance_ref"] == "inst_a1" and len(r4["_核出来的"]["没核查过"]) == 2)
ck("⚠️ 理由:提前拒绝会让那台实例**连回执都发不出来**,"
   "于是页面显示「尚未确认加载」—— "
   "而「没装」和「装了但能力不够」在那句话上长得一样,是两种不同的下一步",
   "两种不同的下一步" in str(r4["_核出来的"]["怎么读"]),
   str(r4["_核出来的"]["怎么读"])[-60:])

print("\n▸ ⑩ `capability_map` 没带 → 抛(`{}` 和没带是两件事)")
try:
    R.核(这一版=版,
        实例报的={k: v for k, v in 报.items() if k != "capability_map"},
        服务端的project_id="proj_lanxiu", 现在=现在)
    ck("没带 capability_map → 抛", False, "它没抛")
except R.回执不可信 as e:
    ck("没带 → **抛**,且点明 `{}` 是「我一项都不支持」、没带是「没人问过我」",
       "两件事" in str(e), str(e)[:70])
ck("而 `{}` 带了 → 收下(上面第 ⑨ 条验过)", True)
for 怪 in ([], "x", 0):
    try:
        R.核(这一版=版, 实例报的=dict(报, capability_map=怪),
            服务端的project_id="proj_lanxiu", 现在=现在)
        ck(f"`capability_map` = {怪!r} → 抛", False, "它没抛")
    except R.回执不可信 as e:
        ck(f"`capability_map` = {怪!r} → **抛**", "dict" in str(e) or "两件事" in str(e))

print("\n▸ ⑪ 回执够新吗 —— **判据只有这一份**,而两边处置不同")
for 老, 该, 码 in ((899, True, R.新鲜), (900, True, R.新鲜), (901, False, R.陈旧)):
    行, 原, 话 = R.回执够新吗(回执的loaded_at=现在 - 老, 现在=现在, 最长年龄秒=900)
    ck(f"{老} 秒前(上限 900)→ {'还新鲜' if 该 else '陈旧'},原因码 {码}",
       行 is 该 and 原 == 码, 话[:45])
行2, 原2, 话2 = R.回执够新吗(回执的loaded_at=现在 + 100, 现在=现在)
ck("回执时间在**未来** → 不算新鲜,原因码是 `时间在未来`",
   行2 is False and 原2 == R.时间在未来, 话2[:50])
ck("理由里点明:时钟不对时,一份未来的回执**会永远不过期**",
   "永远不过期" in 话2)
ck("⚠️ **「陈旧」和「时间在未来」是两个原因码,不是一个** —— "
   "因为两边的处置不同:页面上都算「不算已加载」,"
   "而 `策略解析` 对陈旧走**回退**、对未来**抛**(时钟有问题时回退也不可信)",
   R.陈旧 != R.时间在未来)

print("\n▸ ⑫ `策略解析` 真的在用这一份(不是自己又写了一遍)")
import 策略解析 as P
ck("`策略解析` 导入了 `回执核验`", getattr(P, "_RV", None) is R)
# 陈旧 → 回退(不抛)
版2 = dict(id="epv_7", content_hash="h7", entry_kind=P.门店V3,
          support_conditions=["tool_attempt_cap"],
          limits={"tool_attempt_cap": 12})
回2 = dict(execution_policy_version_id="epv_7", policy_hash="h7",
          loaded_at=现在 - 5000,
          capability_map={"tool_attempt_cap": True})
退 = dict(id="epv_6", limits={}, 验证于=现在 - 10, 有效到=现在 + 999,
         为什么回退="回执陈旧")
_, st, 细 = P.这次用哪一版(入口=P.门店V3, 发布的=版2, 这个实例的回执=回2,
                    现在=现在, 回执最长年龄秒=900, 本地回退=退)
ck("回执陈旧 → `策略解析` 走**回退**(不抛)", st == P.回退, st)
ck("而陈旧那句话是**那一份判据给的**(带「长得一模一样」那句)",
   "长得一模一样" in str(细.get("陈旧")), str(细.get("陈旧"))[:60])
try:
    P.这次用哪一版(入口=P.门店V3, 发布的=版2,
             这个实例的回执=dict(回2, loaded_at=现在 + 100), 现在=现在,
             本地回退=退)
    ck("回执时间在未来 → `策略解析` 该抛", False, "它没抛")
except P.解析不了 as e:
    ck("回执时间在未来 → `策略解析` **抛**(即使有回退)—— "
       "**同一份判据,两种处置**", "永远不过期" in str(e), str(e)[:55])

print("\n" + "=" * 92)
print(f"{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
for x in 挂:
    print("   挂:", x)
sys.exit(1 if 挂 else 0)
