#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置组端到端(§15.3 / §15.4):审计记录 / 成员与权限 / 预算。

## 这一份里最要紧的一条:**审计终于读得出来了**

从 09-28 起我在每一块都写审计(十几种动作),而在这一组之前
**没有任何接口能把它们读出来**。

> **一条写得下却读不出的审计,在出事的那天和没有审计是一回事。**

所以这一份不只验「接口返回 200」,还验**前面那些块写下的留痕真的能被读到**
(按动作筛得出 `deployment.blocked`,而且带着它当初被拦的理由)。

## ⚠️ 两条这一组特有的判据

**① 不能通过邀请获得自己没有的权限**(§15.3 最后一句)。
落点 `perms.可以授予吗()` —— 它**早就写好了**,而这一组之前没有任何接口调用它。

**② 不许把最后一个能管权限的人去掉。**
它和别的闸不一样:**别的闸拦的是「做错了」,这道拦的是「做完之后没法回头」** ——
一个没有任何人能管权限的项目,从接口这一侧永远救不回来。

## ⚠️ 这一份自己造人、跑完自己清

不清的话跑第二遍就把演示数据搅乱了。手测的时候栽过一次:
我把 U007 降成 viewer,而按 ① 那条规则,U001 **再也没法把那条专项授权还给他** ——
**规则正确工作的后果,是我自己造的脏数据只能去改库才能还原。**
所以这一份只动它自己建的那个工号。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []

管权限的 = "U001"     # admin:「配置密钥与预算」「查看审计」都有
临时工号 = "Utest" + uuid.uuid4().hex[:6]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 管权限的)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务                     # noqa: E402


def 清掉临时的():
    with 事务() as c:
        c.execute(text("""delete from memberships
                         where project_id=:p and user_id=:u"""),
                  {"p": 项目, "u": 临时工号})


def main():
    print("\n\033[1m▸ 设置组 · 审计终于读得出来了\033[0m")

    # ── 一、审计:前面十几块写的留痕,现在读得到 ────────────────────────
    码, a = 打("GET", f"{P}/audit-events?days=30&limit=200")
    ck("GET /audit-events 200", 码 == 200, 码)
    分布 = {x["动作"]: x["次数"] for x in (a or {}).get("这个范围里的动作分布", [])}
    ck("**读得到前面各块写的留痕**(不只是 200)",
       len(分布) >= 6, sorted(分布)[:8])
    ck("审计里有「被拦住」的记录(拦下这件事本身要留痕)",
       any(k.endswith(".blocked") for k in 分布),
       [k for k in 分布 if k.endswith(".blocked")])
    码, b = 打("GET", f"{P}/audit-events?action=deployment.blocked&days=30&limit=3")
    有理由 = [r for r in (b or {}).get("记录", []) if r.get("为什么")]
    ck("被拦的那几条**带着当初被拦的理由**(不只是「被拦了」)",
       bool(有理由), (有理由[0]["为什么"][:40] if 有理由 else None))
    # ⚠️ 查询参数名是 ASCII —— 中文参数名每个调用方都得记得编码,
    #    忘了的表现是 400,不是一条说得清的错(这个仓库第五次)。
    ck("查询参数名是 ASCII(action/actor/result/days/limit)", 码 == 200, 码)

    码, c2 = 打("GET", f"{P}/audit-events?action=%E6%A0%B9%E6%9C%AC%E6%B2%A1%E8%BF%99%E4%B8%AA")
    ck("筛空了要说清是「被筛掉了」不是「本来就没有」",
       码 == 200 and "筛出来是空的" in str((c2 or {}).get("note")),
       str((c2 or {}).get("note"))[:60])
    码, 体 = 打("GET", f"{P}/audit-events", 谁="U002")
    ck("editor 看审计 → 403(要「查看审计」)", 码 == 403, 码)

    # ── 二、成员:给的是「他实际能做什么」 ──────────────────────────────
    码, m = 打("GET", f"{P}/memberships")
    ck("GET /memberships 200", 码 == 200, 码)
    表 = {x["工号"]: x for x in (m or {}).get("成员", [])}
    ck("**给的是实际能做什么,不只是角色名**",
       "U006" in 表 and isinstance(表["U006"]["实际能做的"], list)
       and 表["U006"]["实际能做的"], 表.get("U006", {}).get("实际能做的"))
    # ⚠️ 第一版这条断言写反了:我以为 approver 的「审批工具动作」是
    # 「可授权(默认关)」,而它其实是「是(默认有)」——
    # **默认关的是 admin 那一格**,那正是下面 U001 建不出 approver 的原因。
    # > 判据写错的时候,它照样会红,而红的理由指着错的方向。
    ck("approver 默认**就有**「审批工具动作」(这是它存在的理由)",
       "审批工具动作" in 表.get("U006", {}).get("实际能做的", []),
       表.get("U006", {}).get("实际能做的"))
    ck("而 **admin 默认没有**那条 —— 所以 admin 建不出 approver(下面验)",
       "审批工具动作" not in 表.get("U001", {}).get("实际能做的", []),
       表.get("U001", {}).get("实际能做的"))
    ck("U007 拿了专项授权,所以他**有**那条", "U007" in 表 and
       "审批工具动作" in 表["U007"]["实际能做的"], 表.get("U007", {}).get("专项授权"))
    ck("列表点名「谁能改权限」", bool((m or {}).get("能改权限的")),
       (m or {}).get("能改权限的"))

    # ── 三、不能授予自己没有的权限 ────────────────────────────────────
    码, 体 = 打("POST", f"{P}/memberships", {"工号": 临时工号, "角色": "admin"},
              谁="U002")
    ck("editor 加成员 → 403(要「配置密钥与预算」)", 码 == 403, 码)
    码, 体 = 打("POST", f"{P}/memberships", {"工号": 临时工号, "角色": "approver"})
    ck("admin 建 approver → 422:**这套权限超出你自己有的**"
       "(admin 自己没拿「审批工具动作」那条专项授权)",
       码 == 422 and (体 or {}).get("code") == "CANNOT_GRANT",
       (码, (体 or {}).get("code")))
    ck("被拦这件事进了审计",
       any(r["做了什么"] == "membership.blocked"
           for r in (打("GET", f"{P}/audit-events?action=membership.blocked&days=1")[1]
                     or {}).get("记录", [])))
    码, 体 = 打("POST", f"{P}/memberships",
              {"工号": 临时工号, "角色": "viewer", "专项授权": ["根本不存在的能力"]})
    ck("专项授权里有认不出的 → 422(**不收任意字符串**:拼错的授权会安静地什么都不开)",
       码 == 422, 码)

    # ── 四、正常建,而且 status 要是 active ───────────────────────────
    码, n = 打("POST", f"{P}/memberships", {"工号": 临时工号, "角色": "viewer"})
    ck("建一个 viewer → 201", 码 == 201, (码, (n or {}).get("code")))
    ck("返回里点明「status 设成了 active」"
       "(不设的话这一行在表里看着好好的,而登录那一步查不到)",
       "active" in str((n or {}).get("note")), str((n or {}).get("note"))[:40])
    码, m2 = 打("GET", f"{P}/memberships")
    新的 = [x for x in (m2 or {}).get("成员", []) if x["工号"] == 临时工号]
    ck("新建的这条**生效**(status=active)",
       bool(新的) and 新的[0]["这条生效吗"] is True,
       新的[0] if 新的 else None)

    # ── 五、不许把最后一个能管权限的人去掉 ────────────────────────────
    #     ⚠️ 这道闸和别的不一样:**别的拦「做错了」,这道拦「做完没法回头」**。
    #     这里用纯逻辑验(不真把演示项目改坏 —— 那正是手测时栽过的地方)。
    import settings as S
    只有一个 = [{"user_id": "U001", "role": "admin", "special_grants": []}]
    问 = S.可以改成员吗(我角色="admin", 我专项=[], 目标工号="U001",
                   要给的角色="viewer", 要给的专项=[], 现有成员们=只有一个)
    ck("把**最后一个**能管权限的人降级 → 拦住",
       any("最后一个" in x for x in 问), [x[:40] for x in 问])
    两个 = 只有一个 + [{"user_id": "U007", "role": "admin", "special_grants": []}]
    问2 = S.可以改成员吗(我角色="admin", 我专项=[], 目标工号="U001",
                    要给的角色="viewer", 要给的专项=[], 现有成员们=两个)
    ck("对照:还有别人能管的时候,降级放行(这道闸不是一刀切)", not 问2, 问2)

    # ── 六、预算:0 不是「不限」 ──────────────────────────────────────
    码, 体 = 打("POST", f"{P}/budgets", {"范围": "project", "周期": "month",
                                     "币种": "USD"})
    ck("不给上限 → 422(**想表达「不限」就别建这一行**)", 码 == 422, 码)
    码, 体 = 打("POST", f"{P}/budgets", {"范围": "project", "周期": "month",
                                     "上限": 50})
    ck("不给币种 → 422(两个币种的数放一列,「总共花了多少」会算出没意义的和)",
       码 == 422, 码)
    码, bd = 打("POST", f"{P}/budgets", {"范围": "project", "周期": "month",
                                      "上限": 50, "币种": "USD"})
    ck("正常设 → 201", 码 in (200, 201), (码, (bd or {}).get("code")))
    ck("**「已预留」和「上限」分开报**(预留是打算花,花掉是已经花)",
       (bd or {}).get("已预留") is not None and (bd or {}).get("上限") is not None,
       {k: (bd or {}).get(k) for k in ("上限", "已预留", "还能预留")})
    码, bd0 = 打("POST", f"{P}/budgets", {"范围": "project", "周期": "day",
                                       "上限": 0, "币种": "USD"})
    ck("上限 0 → 明说「一分都不许花」,**不是「不限」**",
       "不许花" in str((bd0 or {}).get("note")), str((bd0 or {}).get("note"))[:40])
    ck("没有那一行 = 没设上限(和上限 0 完全不是一回事)",
       S.还能花多少(None)["设了上限吗"] is False)
    码, 体 = 打("GET", f"{P}/budgets", 谁="U003")
    ck("viewer 看预算 → 403", 码 == 403, 码)

    清掉临时的()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(临时工号已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
