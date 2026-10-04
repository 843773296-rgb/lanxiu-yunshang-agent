#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缓存答案「现在还能用吗」—— 零 IO。规格 §13 + 附录 A-3。

## 每一条对着规格 §C.2 里一个场景

那张场景表里这一族占了最多行:入缓存后撤销授权、资料发布与撤回、
清空后旧请求回写、TTL 边界、Redis 逐出但目录仍在。
它们的共同点是**答案还在,而它已经不该被返回了** ——
> 一条不该返回的答案,和一条正常的答案,**在内容上长得一模一样**。

⚠️ **时间用注入的,不读墙钟**(规格 §C.4:「不依赖现实日期漂移」)。
这个仓库为「夹具写死日期」栽过。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "cache"))

import usable as U

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


现在 = 1000          # 注入的时钟,不是墙钟
条 = dict(namespace_generation=7, authorization_epoch=3,
         dependencies={"km": "km_11", "rp": "rp_2"},
         expires_at=现在 + 300, revoked=False, payload_present=True)
权 = dict(namespace_generation=7, authorization_epoch=3,
         dependencies={"km": "km_11", "rp": "rp_2"})

print("缓存答案还能用吗(规格 §13 / 附录 A-3)")
print("=" * 92)

print("\n▸ ① 一切都对 → 可用")
行, 因, _ = U.还能用吗(条目=条, 权威=权, 现在=现在)
ck("代次、授权、依赖都对,没过期,没撤回 → 可用", 行 and 因 == U.可用, 因)

print("\n▸ ② 代次判的是**完全相等**,不是 `>=`(清空后旧请求回写)")
for 权代, 叫法 in ((8, "权威涨到 8(范围被清空过)"), (6, "权威是 6(条目来自更新的代次)")):
    行2, 因2, 细2 = U.还能用吗(条目=条, 权威=dict(权, namespace_generation=权代), 现在=现在)
    ck(f"{叫法} → 不可用", (not 行2) and 因2 == U.代次变了, (因2, 细2.get("现在的")))
ck("**而且理由里写明了「不是 >=」** —— 写成 `>=` 的话旧代次的值对新代次就可读了",
   ">=" in str(U.还能用吗(条目=条, 权威=dict(权, namespace_generation=8),
                      现在=现在)[2]))

print("\n▸ ③ 授权代次变了 → 不可用,**不等 Redis 物理删除**")
行3, 因3, 细3 = U.还能用吗(条目=条, 权威=dict(权, authorization_epoch=4), 现在=现在)
ck("撤权后(epoch 3→4)→ 不可用", (not 行3) and 因3 == U.授权变了, 因3)
ck("理由里明说不等物理删除(规格 §C.2「入缓存后撤销授权」)",
   "物理删除" in str(细3), str(细3)[:80])

print("\n▸ ④ **未知 ≠ 没变** —— 依赖版本拿不到就不可用")
for 权依, 叫法 in (({"km": "km_11"}, "权威里少了 rp"),
                ({"km": "km_11", "rp": None}, "权威里 rp 是 None")):
    行4, 因4, 细4 = U.还能用吗(条目=条, 权威=dict(权, dependencies=权依), 现在=现在)
    ck(f"{叫法} → 不可用(**不假定它没变**)",
       (not 行4) and 因4 == U.依赖未知, (因4, 细4.get("拿不到的")))

print("\n▸ ⑤ 依赖变了 → 不可用;而**权威多出来的依赖不算变**")
行5, 因5, 细5 = U.还能用吗(条目=条,
                    权威=dict(权, dependencies={"km": "km_12", "rp": "rp_2"}),
                    现在=现在)
ck("资料版本 km_11→km_12 → 不可用,而且点名是哪一个变了",
   (not 行5) and 因5 == U.资料变了 and "km" in str(细5.get("变了的")), 细5.get("变了的"))
行6, 因6, 细6 = U.还能用吗(条目=条,
                    权威=dict(权, dependencies={**权["dependencies"], "新的": "x1"}),
                    现在=现在)
ck("权威**多出来**一个依赖 → **仍然可用**(这条答案当初没用到它)",
   行6 and 因6 == U.可用, 细6.get("权威多出来的依赖"))
ck("**不这么算的话,新加一个依赖会让全部旧条目一起失效**",
   "一起失效" in str(细6), str(细6.get("怎么读"))[:60])

print("\n▸ ⑥ 过期是**严格小于**,边界偏保守那一边")
到 = 条["expires_at"]
for t, 该行 in ((到 - 1, True), (到, False), (到 + 1, False)):
    行7, 因7, _ = U.还能用吗(条目=条, 权威=权, 现在=t)
    ck(f"现在={t}(到期={到})→ {'可用' if 该行 else '过期'}",
       行7 is 该行 and (因7 == U.可用 if 该行 else 因7 == U.过期), 因7)
ck("**`现在 == 到期` 算已过期** —— 偏错的代价不对称:"
   "多生成一次只多花钱,少失效一次是**错答案**",
   U.还能用吗(条目=条, 权威=权, 现在=到)[1] == U.过期)

print("\n▸ ⑦ 撤回**压倒一切**(没过期、代次对、依赖都对也不行)")
行8, 因8, 细8 = U.还能用吗(条目=dict(条, revoked=True), 权威=权, 现在=现在)
ck("撤回了 → 不可用", (not 行8) and 因8 == U.被撤回, 因8)
ck("而且理由是**撤回**,不是过期 —— 排行榜上这两个该引向不同的下一步",
   因8 != U.过期 and "旧值还在也不能返回" in str(细8), str(细8)[:70])

print("\n▸ ⑧ 目录有记录而负载没了 → 按未命中处理,**不返回空白伪答案**")
行9, 因9, _ = U.还能用吗(条目=dict(条, payload_present=False), 权威=权, 现在=现在)
ck("Redis 逐出而目录仍在 → 不可用(规格 §C.2)",
   (not 行9) and 因9 == U.负载没了, 因9)

print("\n▸ ⑨ 缺字段 / 拿不到权威状态 → **抛**,不判可用")
for 去掉 in ("namespace_generation", "authorization_epoch", "expires_at"):
    try:
        U.还能用吗(条目={k: v for k, v in 条.items() if k != 去掉}, 权威=权, 现在=现在)
        ck(f"条目缺 `{去掉}` → 抛", False, "它没抛")
    except U.判不了 as e:
        ck(f"条目缺 `{去掉}` → 抛(**不拿默认值顶**)", 去掉 in str(e), str(e)[:70])
try:
    U.还能用吗(条目=条, 权威={"namespace_generation": None}, 现在=现在)
    ck("拿不到权威代次 → 抛", False, "它没抛")
except U.判不了 as e:
    ck("拿不到权威状态 → **抛**(不许判可用,由调用方决定绕过还是拒绝)",
       "不许判可用" in str(e), str(e)[:70])
try:
    U.还能用吗(条目=dict(条, expires_at=None), 权威=权, 现在=现在)
    ck("`expires_at` 是 None → 抛", False, "它没抛")
except U.判不了 as e:
    ck("`expires_at=None` → **抛**(没有有效期不等于永久有效)",
       "不等于永久有效" in str(e), str(e)[:70])

print("\n▸ ⑩ 写入要**再核一次** —— 生成期间代次可能变了")
行10, 话10 = U.能写进去吗(要写的代次=7, 权威代次=7, 要写的授权代次=3, 权威授权代次=3)
ck("开始和结束时代次都一样 → 可以写", 行10, 话10)
行11, 话11 = U.能写进去吗(要写的代次=7, 权威代次=8, 要写的授权代次=3, 权威授权代次=3)
ck("生成期间范围被清空(7→8)→ **不写进新代次**", (not 行11) and "清空" in 话11, 话11)
行12, 话12 = U.能写进去吗(要写的代次=7, 权威代次=7, 要写的授权代次=3, 权威授权代次=4)
ck("生成期间授权变过 → **禁止缓存旧结果**", (not 行12) and "禁止缓存" in 话12, 话12)
ck("⚠️ 这一条和读那一次是**两次核对** —— "
   "只在读的时候核过的实现,和两头都核的,**在正常情况下长得一模一样**,"
   "差别只在清空那一瞬间出现", True)

print("\n" + "=" * 92)
print(f"{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
for x in 挂:
    print("   挂:", x)
sys.exit(1 if 挂 else 0)
