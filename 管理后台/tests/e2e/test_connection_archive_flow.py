#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型连接**停用 / 启用**(connections_api.archive / unarchive,11-18 补的接口)。

## 为什么要这一份

在这之前**没有任何接口能停用一条连接**:建连接那道闸的建议写着「先把那条停用或归档」,
而那件事只能靠直接写库(e2e 测试就是这么干的)——
> 一句指着不存在的动作的建议,比不给建议更糟:读起来完全合理,照着做做不到。

## 守的几条

  · 不带 If-Match → 409 IF_MATCH_REQUIRED;错的 → 409 REVISION_CONFLICT;对的 → 200 status=archived
  · 列表默认不列停用的,`?含停用=true` 才列(要「启用」它得先看得见它)
  · 重复停用 → 不改、照实说(改了吗=False)
  · 启用时同用途已有别的 active → 409 PURPOSE_TAKEN(和建连接那道闸同一个口径:用途不并存两条在用的)
  · 审计里有 model_connection.archive

⚠️ 前提 `make dev`。自己建连接(用途 finetune_infer,demo 里没人占;避开 test_connections_flow 用的 rerank,
两份可能并发跑),跑完**留在 archived** —— 那就是清理。只碰 project_demo_a;库只读(审计那条查 audit_events)。
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
配密钥的 = "U001"
用途 = "finetune_infer"
尾 = uuid.uuid4().hex[:6]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 配密钥的)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
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
from db import 连接                     # noqa: E402


def 列表(含停用=False):
    s, b = 打("GET", P + "/model-connections" + ("?含停用=true" if 含停用 else ""))
    return s, {x["id"]: x for x in (b or {}).get("连接", [])}, b


def 建(名):
    return 打("POST", P + "/model-connections",
              {"用途": 用途, "适配器": "MockModelProvider", "名字": 名,
               "endpoint": "mock://e2e-archive", "secret_ref": f"keychain://lanxiu/e2e-archive-{尾}"})


def main():
    print("\n\033[1m▸ 模型连接停用 / 启用 · 乐观锁 + 用途不并存\033[0m")
    建了 = []
    # ── 0. 前提:这个用途在项目里现在没人占(否则建不出来,后面全空验)──
    s, 现, _ = 列表()
    占着 = [x["id"] for x in 现.values() if x.get("用途") == 用途 and x.get("状态") == "active"]
    ck(f"前提:用途 {用途} 现在没有启用的连接(有的话多半是上一轮没清干净 —— 要人看)", not 占着, 占着)

    # ── 1. 建一条 → 列表里是 active ──────────────────────────────────────
    s, a = 建(f"e2e 停用启用-A-{尾}")
    ck("建 A → 201", s == 201 and (a or {}).get("id"), (s, (a or {}).get("code")))
    aid = (a or {}).get("id")
    if aid:
        建了.append(aid)
    s, 现, _ = 列表()
    ck("建完默认列表里有 A、状态 active、带 revision", aid in 现 and 现[aid]["状态"] == "active"
       and isinstance(现[aid].get("revision"), int), 现.get(aid, {}).get("状态"))
    rev = (现.get(aid) or {}).get("revision")

    # ── 2. 乐观锁三连 ───────────────────────────────────────────────────
    s, b = 打("POST", P + f"/model-connections/{aid}/archive")
    ck("停用不带 If-Match → 409 IF_MATCH_REQUIRED", s == 409 and (b or {}).get("code") == "IF_MATCH_REQUIRED",
       (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": "9999"})
    ck("错的 If-Match → 409 REVISION_CONFLICT", s == 409 and (b or {}).get("code") == "REVISION_CONFLICT",
       (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": str(rev)})
    ck("对的 If-Match → 200 status=archived、改了吗=True、revision 前进一格",
       s == 200 and (b or {}).get("status") == "archived" and (b or {}).get("改了吗") is True
       and (b or {}).get("revision") == rev + 1, (s, b))
    ck("note 不许写「已发布版本不受影响」—— 停用后凡用到它的每一跑都会失败,那不是真的",
       "不受影响" not in ((b or {}).get("note") or "").replace("知识索引不受影响", "") and "MODEL_CONNECTION_DISABLED" in ((b or {}).get("note") or ""),
       ((b or {}).get("note") or "")[:120])
    rev2 = (b or {}).get("revision")

    # ── 3. 列表:默认不列,含停用才列 ──────────────────────────────────
    s, 默认, 体默认 = 列表()
    ck("默认列表**不列**停用的 A,而且「停用的条数」≥ 1(列表自己说有多少条没列)",
       aid not in 默认 and (体默认 or {}).get("停用的条数", 0) >= 1 and (体默认 or {}).get("含停用") is False,
       {"在不在": aid in 默认, "停用的条数": (体默认 or {}).get("停用的条数")})
    s, 含, 体含 = 列表(含停用=True)
    ck("`?含停用=true` 列出 A,状态 archived、带「停用于」时间",
       aid in 含 and 含[aid]["状态"] == "archived" and bool(含[aid].get("停用于")),
       {k: 含.get(aid, {}).get(k) for k in ("状态", "停用于")})

    # ── 4. 重复停用:不改、照实说 ──────────────────────────────────────
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": str(rev2)})
    ck("已经停用的再停一次 → 200 改了吗=False、revision 不动",
       s == 200 and (b or {}).get("改了吗") is False and (b or {}).get("revision") == rev2, (s, b))
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": "1"})
    ck("重复停用**连 If-Match 对不对都不看**(已经是目标状态,没有要保护的写)—— 照实说 改了吗=False",
       s == 200 and (b or {}).get("改了吗") is False, (s, (b or {}).get("code") or (b or {}).get("改了吗")))

    # ── 5. 同用途另建一条 B(A 已停用所以建得出来)→ 启用 A 撞 PURPOSE_TAKEN ──
    s, bb = 建(f"e2e 停用启用-B-{尾}")
    ck("A 停用后同用途能再建 B(对照:停用真的把用途让出来了)", s == 201 and (bb or {}).get("id"),
       (s, (bb or {}).get("code")))
    bid = (bb or {}).get("id")
    if bid:
        建了.append(bid)
    s, b = 打("POST", P + f"/model-connections/{aid}/unarchive", 头={"If-Match": str(rev2)})
    ck("B 在用时启用 A → 409 PURPOSE_TAKEN(用途不并存两条在用的)",
       s == 409 and (b or {}).get("code") == "PURPOSE_TAKEN", (s, (b or {}).get("code")))
    ck("advice 点名了撞的是哪条、而且说清为什么不并存", bid in json.dumps(b or {}, ensure_ascii=False)
       and "不并存" in ((b or {}).get("advice") or ""), ((b or {}).get("advice") or "")[:100])
    s, b = 打("POST", P + f"/model-connections/{aid}/unarchive")
    ck("启用不带 If-Match → 409 IF_MATCH_REQUIRED(和停用同一道锁)",
       s == 409 and (b or {}).get("code") == "IF_MATCH_REQUIRED", (s, (b or {}).get("code")))

    # ── 6. 把 B 停用 → 启用 A 成功 → 再把 A 停用(清理:两条都留在 archived)──
    s, 含, _ = 列表(含停用=True)
    s, b = 打("POST", P + f"/model-connections/{bid}/archive", 头={"If-Match": str(含[bid]["revision"])})
    ck("停用 B → 200 archived", s == 200 and (b or {}).get("status") == "archived", (s, b))
    s, b = 打("POST", P + f"/model-connections/{aid}/unarchive", 头={"If-Match": str(rev2)})
    ck("B 停用后启用 A → 200 status=active、改了吗=True(对照:上面那条 409 不是恒拦)",
       s == 200 and (b or {}).get("status") == "active" and (b or {}).get("改了吗") is True, (s, b))
    ck("启用的 note 说清「不用重探,但没探过的照旧没探过」", "重探" in ((b or {}).get("note") or ""),
       ((b or {}).get("note") or "")[:100])
    rev3 = (b or {}).get("revision")
    s, 现, _ = 列表()
    ck("启用后默认列表又列出 A 了、停用于清空", aid in 现 and 现[aid]["状态"] == "active" and not 现[aid].get("停用于"),
       {k: 现.get(aid, {}).get(k) for k in ("状态", "停用于")})
    s, b = 打("POST", P + f"/model-connections/{aid}/unarchive", 头={"If-Match": str(rev3)})
    ck("已经在用的再启用一次 → 改了吗=False", s == 200 and (b or {}).get("改了吗") is False, (s, b))
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": str(rev3)}, 谁="U002")
    ck("editor(U002)停用 → 403(要「配置密钥与预算」)", s == 403, (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/model-connections/{aid}/archive", 头={"If-Match": str(rev3)})
    ck("清理:A 再停用 → 200 archived(两条都留在 archived,下一轮才建得出来)",
       s == 200 and (b or {}).get("status") == "archived", (s, b))

    # ── 7. 审计 ─────────────────────────────────────────────────────────
    with 连接() as c:
        审 = [tuple(r) for r in c.execute(text("""
            select action, target_ref->>'connection_id', target_ref->>'到' from audit_events
             where project_id=:p and action in ('model_connection.archive','model_connection.unarchive')
               and target_ref->>'connection_id' = any(:ids) order by at"""),
            {"p": 项目, "ids": 建了})]
    停了 = [x for x in 审 if x[0] == "model_connection.archive"]
    启了 = [x for x in 审 if x[0] == "model_connection.unarchive"]
    ck("审计里有 model_connection.archive(A 两次 + B 一次 = 3 条;重复停用那两次**不记** —— 没改就没有事)",
       len(停了) == 3 and all(x[2] == "archived" for x in 停了), 审)
    ck("审计里有 model_connection.unarchive(A 成功那一次 = 1 条;409 和重复启用不记)",
       len(启了) == 1 and 启了[0][1] == aid, 启了)

    s, 含, _ = 列表(含停用=True)
    留 = {i: 含.get(i, {}).get("状态") for i in 建了}
    ck("收尾:这一轮建的都在 archived(**停用就是清理**,不另写库)", 建了 and all(v == "archived" for v in 留.values()), 留)

    print(f"\n{'✅ ' + str(len(过)) + ' 条全过' if not 挂 else '❌ 挂: ' + str(挂)}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
