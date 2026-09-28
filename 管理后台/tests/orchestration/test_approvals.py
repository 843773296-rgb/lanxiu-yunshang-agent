#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工审批的判断 —— **零 IO,跑在 CI 里**。

## 这一组守的是一道「**拦得住但没有放行入口**」的闸

`runtime/tool_gateway.py` 早就在拦不可逆写入了,而 2026-09-28 之前
**没有任何代码能生产一条批准** —— 被拦住的东西永远出不去。
而它在检查上是绿的:「没有生效批准的不可逆写入被挡住」照样过。

> **一道拦得住但没有放行入口的闸,是一个做了一半的机制。**

## 八条判断,每条的坏法都不报错

    ① 模型不能批准自己            能自批的 Agent = 没有审批
    ② 发起人不能自批(比契约严)    同上
    ③ 一次请求只能被处理一次      两个人同点,第二个覆盖第一个
    ④ 过期在**点批准那一刻**比    建请求时比 → 三天前的请求今天还能批
    ⑤ 没设过期 ≠ 永不过期        忘了设过期的高危请求会永远可批
    ⑥ 有审批角色 ≠ 能碰这个对象
    ⑦ 敏感字段一律不许编辑        即使它被写进了 allowed_fields
    ⑧ **候选角色里得真有人能审**  否则请求建出来就没人能批,而列表上看着正常
"""
import datetime as dt
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))

import approvals as A

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


现 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
基 = dict(status=A.待处理, expires_at=现 + dt.timedelta(hours=6),
        candidate_roles=["approver", "admin"], created_by="U001", revision=1,
        arguments_hash="h1", allowed_fields=["content"])
好参 = dict(谁="U006", 他的角色="approver", 现在=现, 他能碰这个对象吗=True)

print("▸ ① 模型不能批准自己(§9.6)")
ck("是模型 → 拒", not A.能处理吗(基, **好参, 是模型吗=True)[0])
ck("理由点明「能自批的 Agent 等于没有审批」",
   "等于没有审批" in A.能处理吗(基, **好参, 是模型吗=True)[1])
ck("**这一条排在最前面**:它和请求状态无关,而且它最贵 —— "
   "一条终态的请求给模型看,报的也该是这个",
   "模型" in A.能处理吗({**基, "status": A.已批准}, **好参, 是模型吗=True)[1])

print("▸ ② 发起人不能自批(**比契约严**)")
ck("发起人自己批 → 拒", not A.能处理吗(基, 谁="U001", 他的角色="approver",
                                现在=现, 他能碰这个对象吗=True)[0])
ck("而且明说这一条比契约严(契约只禁了模型自批)",
   "比契约严" in A.能处理吗(基, 谁="U001", 他的角色="approver",
                       现在=现, 他能碰这个对象吗=True)[1])

print("▸ ③ 一次请求只能被处理一次")
for st in (A.已批准, A.已驳回, A.已过期, A.已取消):
    ck(f"{st} → 拒", not A.能处理吗({**基, "status": st}, **好参)[0])
ck("理由说清「两个人同点时第二个该看到这个,而不是覆盖第一个」",
   "覆盖第一个" in A.能处理吗({**基, "status": A.已批准}, **好参)[1])
ck("`info_requested` **可以**再处理(补完之后要重新批)",
   A.能处理吗({**基, "status": A.要求补充}, **好参)[0])
ck("认不出的状态 → 拒", not A.能处理吗({**基, "status": "随便编的"}, **好参)[0])

print("▸ ④ 过期在**点批准那一刻**比,不是建请求的时候")
ck("在期内 → 放行", A.能处理吗(基, **好参)[0])
ck("过了截止时间 → 拒",
   not A.能处理吗({**基, "expires_at": 现 - dt.timedelta(minutes=1)}, **好参)[0])
ck("**刚好卡在截止时间上算过期**(>=,不是 >)",
   A.过期了吗(现, 现) is True)
ck("差一秒还没过期", A.过期了吗(现 + dt.timedelta(seconds=1), 现) is False)
ck("**「现在」是参数不是自己取** —— 自己取就测不了边界",
   "现在" in A.过期了吗.__code__.co_varnames)
try:
    A.过期了吗(现, None)
    ck("缺「现在」→ 抛", False, "没抛!")
except A.不能处理:
    ck("缺「现在」→ 当场抛(不许自己取当前时间)", True)

print("▸ ⑤ 没设过期 **≠** 永不过期")
ck("expires_at 是 None → `过期了吗` 返回 **None**(第三档,不是 False)",
   A.过期了吗(None, 现) is None)
ck("而 `能处理吗` 把这一档判成**拒**",
   not A.能处理吗({**基, "expires_at": None}, **好参)[0])
ck("理由说清「一条忘了设过期的高危请求会永远可批」",
   "永远可批" in A.能处理吗({**基, "expires_at": None}, **好参)[1])

print("▸ ⑥ 有审批角色 ≠ 能碰这个对象")
ck("角色不在候选里 → 拒",
   not A.能处理吗(基, 谁="U006", 他的角色="editor", 现在=现, 他能碰这个对象吗=True)[0])
ck("对象没权限 → 拒",
   not A.能处理吗(基, 谁="U006", 他的角色="approver", 现在=现, 他能碰这个对象吗=False)[0])
ck("**不告诉我有没有对象权限 → 也拒**(不默认有)",
   not A.能处理吗(基, 谁="U006", 他的角色="approver", 现在=现,
                他能碰这个对象吗=None)[0])
ck("而且说清「不默认有」是有意的",
   "不默认有" in A.能处理吗(基, 谁="U006", 他的角色="approver", 现在=现,
                       他能碰这个对象吗=None)[1])

print("▸ ⑦ 编辑:白名单 + 敏感字段一律拒")
ck("没改东西 → 没问题", A.查编辑({}, ["content"]) == [])
ck("改白名单里的 → 没问题", A.查编辑({"content": "x"}, ["content"]) == [])
ck("改白名单外的 → 拒", bool(A.查编辑({"path": "/tmp"}, ["content"])))
ck("**没声明 allowed_fields = 一个都不许改**,不是随便改",
   bool(A.查编辑({"content": "x"}, [])), A.查编辑({"content": "x"}, []))
for 键 in ("secret_ref", "api_key", "project_id", "owner_id", "role", "acl"):
    ck(f"`{键}` **写进白名单也拒**(白名单可能是配错的)",
       bool(A.查编辑({键: "x"}, [键])), A.查编辑({键: "x"}, [键])[:1])

print("▸ ⑧ 候选角色里得**真有人能审**")
ck("候选里有 approver → 行", A.候选角色里有人能审吗(["approver", "admin"], ["approver"])[0])
ck("候选里一个能审的都没有 → 拒",
   not A.候选角色里有人能审吗(["editor", "viewer"], ["approver"])[0])
ck("理由说清「建出来就没人能批,而它在列表上看起来完全正常」",
   "看起来完全正常" in A.候选角色里有人能审吗(["editor"], ["approver"])[1])
ck("候选是空的 → 拒(**那不是「谁都能审」,是没写该找谁审**)",
   not A.候选角色里有人能审吗([], ["approver"])[0])
ck("理由里说清这个区别", "没写该找谁审" in A.候选角色里有人能审吗([], ["approver"])[1])

print("▸ ⑨ 算批准:折成闸要的那个形状")
决定 = [dict(decision=A.已批准, actor="U006", request_revision=1)]
r = A.算批准({**基, "status": A.已批准, "revision": 2}, 决定, 现在=现)
ck("状态 approved + 有批准记录 → 算得出",
   r == {"参数摘要": "h1", "批准人": "U006", "过期了吗": False}, r)
ck("**不要求 request_revision 等于当前 revision** —— "
   "批准这个动作本身就会让 revision 前进,那样永远算不出来",
   r is not None)
ck("状态不是 approved → None",
   A.算批准(基, 决定, 现在=现) is None)
ck("状态是 approved 但一条批准记录都没有 → None(库不一致,不放行)",
   A.算批准({**基, "status": A.已批准}, [], 现在=现) is None)
后来要求补充 = 决定 + [dict(decision=A.要求补充, actor="U006", request_revision=2)]
ck("**批准之后又「要求补充」→ 批准失效**(旧批准对新参数无效)",
   A.算批准({**基, "status": A.已批准}, 后来要求补充, 现在=现) is None)
再批 = 后来要求补充 + [dict(decision=A.已批准, actor="U006", request_revision=3)]
ck("补完之后重新批 → 又算得出(取最后一条)",
   (A.算批准({**基, "status": A.已批准}, 再批, 现在=现) or {}).get("批准人") == "U006")
过期的 = A.算批准({**基, "status": A.已批准,
                "expires_at": 现 - dt.timedelta(minutes=1)}, 决定, 现在=现)
ck("**过期了仍然返回形状,但标 `过期了吗=True`** —— "
   "闸自己会拒,而「过期的批准」和「没有批准」是两件事,理由不同",
   过期的 is not None and 过期的["过期了吗"] is True, 过期的)
ck("**参数摘要原样取请求上的,不在这里重算** —— "
   "两个地方各算一次,一次合法的重试就会被判成「参数变了」",
   r["参数摘要"] == 基["arguments_hash"])

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
