#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选策略六条接口 · **配置面,而检索还没做**。

## ⚠️ 这一份最先要守的那句话

规格 §16 第四阶段是「关键词筛选」—— 而这一块只做**策略配置**那一半,
**不碰 `agent_loop`**。所以每条接口的返回里都带 `⚠️还没生效`:

> 一个配得出来而没人消费的策略,和一个生效了的策略,
> **在界面上长得一模一样** —— 所以那句话必须在。

这一份断那句话在不在。少了它,下一个人会以为策略已经在跑。

## 六道闸各防一件不同的事

| 闸 | 不拦的话会怎样 |
|---|---|
| 扩展模式(hybrid / 原生) | 配得出来、冻得进去,**而运行时压根不认** |
| 关键词模式不绑快照 | 它拿什么去检索?而「没绑」和「绑了个空的」长得一样 |
| **单次额度 > 活动总额** | 那个单次上限**永远碰不到** —— 它看起来在限制什么,实际不限制任何东西 |
| 开候选缓存 | A-7 首版关闭;而开了之后少复核一样,**一条被撤回的授权会靠缓存继续生效** |
| 塞身份/密钥类键 | 一个能改策略的人就能通过策略影响授权 |
| 快照不是「已就绪」 | 半建好的索引绑上去,表现是「某些工具搜不到」而不是报错 |

⚠️ 前提 `make dev`。自己造策略,跑完自己清。
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
尾 = uuid.uuid4().hex[:6]
限 = {"initial_candidates": 5, "new_definition_tokens": 4000,
     "active_definition_tokens": 12000, "max_rediscovery": 2,
     "selection_timeout_ms": 3000}
组版本 = "tgv_先查后写_v1"      # seed 铺的


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U002", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
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
from db import 事务                     # noqa: E402


def 清掉():
    with 事务() as c:
        c.execute(text("""delete from tool_selection_policy_versions
                        where project_id=:p and tool_selection_policy_id in (
                          select id from tool_selection_policies
                           where project_id=:p and name like :n)"""),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("""delete from tool_selection_policies
                        where project_id=:p and name like :n"""),
                  {"p": 项目, "n": f"%{尾}"})
        # ⚠️ 第七节自己造的三个「真东西」也要清 ——
        # 不清的话**跑第二遍会撞主键**,而那个失败看起来像接口坏了。
        # (「跑得起第二遍」和「不留垃圾」是两件事,这仓库撞过五次。)
        # 按**名字里的随机尾**清,不按 id 前缀 —— id 这几条是我自己拼的,
        # 但按名字清和别的夹具一致,而且下次有人改成服务端生成也不会失效。
        c.execute(text("""delete from connection_versions
                        where project_id=:p and connection_id in (
                          select id from model_connections
                           where project_id=:p and display_name like :n)"""),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("""delete from model_connections
                        where project_id=:p and display_name like :n"""),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("""delete from capability_connections
                        where project_id=:p and name like :n"""),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("""delete from evaluations
                        where project_id=:p and id like :i"""),
                  {"p": 项目, "i": f"ev_假的{尾}"})


def main():
    print("\n\033[1m▸ 筛选策略 · 配置面(检索还没做)\033[0m")
    基 = dict(模式="fixed_group", 默认工具组版本=组版本, 限额=限,
             没结果怎么办="stop", 目录出错怎么办="stop")

    print("\n▸ 一、建策略 + **「还没生效」那句话**")
    码, 体 = 打("POST", f"{P}/tool-selection-policies", {"名称": f"t{尾}"})
    ck("不写用途 → 422(一个说不出用途的策略,下次没人知道它为什么长这样)",
       码 == 422, {"码": 码})
    码, pol = 打("POST", f"{P}/tool-selection-policies",
               {"名称": f"策略{尾}", "用途": "验六道闸"})
    ck("建策略 → 201", 码 == 201, {"码": 码})
    pid = (pol or {}).get("id")
    # ⚠️ 这一条是这一份最先要守的:**检索还没做,而策略配得出来**。
    ck("**建完就明说「还没有任何东西在消费它」**"
       "(一个配得出来而没人消费的策略,和一个生效了的,"
       "在界面上长得一模一样)",
       "还没有任何东西在消费" in str((pol or {}).get("⚠️还没生效") or ""),
       str((pol or {}).get("⚠️还没生效") or "")[:40])
    if not pid:
        print(f"\n❌ 过 {len(过)} / 挂 {len(挂)}(建不出策略,**没往下跑**)")
        return 1
    码, 列 = 打("GET", f"{P}/tool-selection-policies")
    ck("列表给出**可选模式,并标明哪些首版支持**"
       "(前端硬编会和这张表漂)",
       any(x.get("首版支持吗") is True for x in ((列 or {}).get("可选模式") or []))
       and any(x.get("首版支持吗") is False
               for x in ((列 or {}).get("可选模式") or [])),
       [(x["值"], x["首版支持吗"]) for x in ((列 or {}).get("可选模式") or [])])
    ck("**明说那两个动作别混**(目录里没有 vs 目录取不到 —— "
       "合成一个的话,一次索引故障会被当成「这任务没有可用工具」)",
       "索引故障" in str((列 or {}).get("⚠️两个动作别混") or ""),
       str((列 or {}).get("⚠️两个动作别混") or "")[:40])

    print("\n▸ 二、六道闸:**各防一件不同的事**")

    def 校(配, 名, 关键词):
        码, d = 打("POST", f"{P}/tool-selection-policies/{pid}/validate", 配)
        问 = (d or {}).get("问题") or []
        ck(名, 码 == 200 and (d or {}).get("过了吗") is False
           and any(关键词 in x for x in 问),
           {"码": 码, "问题": [x[:50] for x in 问][:1]})

    校({**基, "模式": "hybrid"},
      "扩展模式 hybrid → 不过(**配得出来、冻得进去,而运行时压根不认**)",
      "首版不支持")
    校({**基, "模式": "keyword_search", "默认工具组版本": None},
      "关键词模式不绑快照 → 不过(它拿什么去检索?"
      "而「没绑」和「绑了个空的」在配置上长得一样)",
      "必须绑一个目录快照")
    校({**基, "限额": {**限, "new_definition_tokens": 99999,
                   "active_definition_tokens": 100}},
      "**单次额度 > 活动总额 → 不过**(那个单次上限永远碰不到 —— "
      "它看起来在限制什么,实际不限制任何东西)",
      "永远碰不到")
    校({**基, "开候选缓存": True},
      "开候选缓存 → 不过(A-7 首版关闭;而少复核一样,"
      "**一条被撤回的授权会靠缓存继续生效**)",
      "首版不许开候选缓存")
    校({**基, "principal": "U001", "api_key": "x"},
      "塞身份/密钥类键 → 不过(一个能改策略的人就能通过策略影响授权)",
      "不许进策略")
    校({**基, "限额": {k: v for k, v in 限.items()
                   if k != "initial_candidates"}},
      "少给一个限额 → 不过(**不给默认值**:一个猜出来的预算"
      "会在它不够用那天表现成「模型没看到那个工具」,而不报错)",
      "没给")
    码, d = 打("POST", f"{P}/tool-selection-policies/{pid}/validate", 基)
    ck("**对照:全对 → 过**(一个什么都拦的校验器过不了这一条)",
       码 == 200 and (d or {}).get("过了吗") is True, (d or {}).get("问题"))
    ck("**明说「校验过了不等于冻得进去」**"
       "(中间可能有人把那个快照归档了)",
       "通行证" in str((d or {}).get("⚠️校验过了不等于冻得进去") or ""),
       str((d or {}).get("⚠️校验过了不等于冻得进去") or "")[:40])

    print("\n▸ 三、冻结:**不改变生产引用**")
    码, 体 = 打("POST", f"{P}/tool-selection-policies/{pid}/versions",
             {**基, "模式": "hybrid"})
    ck("冻一个扩展模式的 → 422(校验在冻结时**再跑一遍**)", 码 == 422, {"码": 码})
    码, v = 打("POST", f"{P}/tool-selection-policies/{pid}/versions",
             {**基, "变更说明": "首版:固定工具组"})
    ck("全对 → 201", 码 == 201, {"码": 码})
    ck("**明说冻结不改变生产引用**(「我能改它」和「我能让它生效」是两件事)",
       "发布" in str((v or {}).get("⚠️冻结不改变生产引用") or ""),
       str((v or {}).get("⚠️冻结不改变生产引用") or "")[:36])
    码, det = 打("GET", f"{P}/tool-selection-policies/{pid}")
    ck("详情里版本历史有那一版,而且限额那几个数都在",
       码 == 200 and ((det or {}).get("版本历史") or [])
       and ((det or {}).get("版本历史") or [])[0].get("限额", {}).get(
           "initial_candidates") == 5,
       ((det or {}).get("版本历史") or [{}])[0].get("限额"))
    码, 体 = 打("PATCH", f"{P}/tool-selection-policies/{pid}/draft",
             {"用途": "改一下"})
    ck("改草稿不带 If-Match → 409", 码 == 409, {"码": 码})
    rev = (det or {}).get("draft_revision")
    码, 体 = 打("PATCH", f"{P}/tool-selection-policies/{pid}/draft",
             {"用途": "改好了"}, 头={"If-Match": str(rev)})
    ck("带对的 If-Match → 200 且 draft_revision 涨了",
       码 == 200 and (体 or {}).get("draft_revision") == (rev or 0) + 1,
       {"前": rev, "后": (体 or {}).get("draft_revision")})
    码, 体 = 打("POST", f"{P}/tool-selection-policies",
             {"名称": f"editor 建不了{尾}", "用途": "x"}, 谁="U003")
    ck("viewer 建策略 → 403(要「改筛选策略」这条能力)", 码 == 403, {"码": 码})

    # ── 开独立路由那四道闸(2026-10-03 加)──────────────────────────
    #
    # 规格 §4.2 给的是**条件**不是开关:
    # 「**只有实验证明额外分类有价值时,才启用独立路由节点**」。
    # 在这之前 `independent_router_enabled` 一道闸都没有 —— 只是 bool() 收下来。
    # > 一个没有实验撑着的「已启用」,和一个有实验撑着的,在策略页上长得一模一样。
    #
    # ⚠️ **每条反例只破坏一件事**,其余字段全合法 ——
    # 不然前面的闸先拦住,这几道根本走不到。
    # (第一次手撞这几道闸就栽在这上面:报出来的全是「没结果怎么办」没给,
    #  四道路由闸一道都没走到,而输出看起来像「全红了」。)
    print("\n▸ 七、开独立路由的四道闸(规格 §4.2 的「实验」变成结构)")
    # 三个**真东西** —— 不造的话下面几条断言测不到行为,只测到提示文案里有几个字
    from sqlalchemy import text as _t
    from db import 事务 as _事务
    with _事务() as _c:
        _org = _c.execute(_t("select organization_id from projects where id=:p"),
                          {"p": 项目}).scalar()
        真工具连接 = f"cc_假的{尾}"
        _c.execute(_t("""insert into capability_connections
            (id, organization_id, project_id, name, adapter, allowed_endpoints,
             secret_ref, status, owner, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,'MockAdapter', cast('[]' as jsonb),
                    'keychain://x','active','test', now(),'test', now(), 1)"""),
                   {"i": 真工具连接, "o": _org, "p": 项目,
                    "n": f"工具连接-给闸测用{尾}"})
        # 一条**已完成且有基线**的评测 —— 闸要求的就是这个形状
        真实验 = f"ev_假的{尾}"
        _c.execute(_t("""insert into evaluations
            (id, organization_id, project_id, candidate_ref, baseline_ref,
             dataset_version_id, scorer_version, status,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p, cast('{"ref":"候选"}' as jsonb),
                    cast('{"ref":"基线"}' as jsonb), null, 'v1', '已完成',
                    now(),'test', now(), 1)"""),
                   {"i": 真实验, "o": _org, "p": 项目})
        真模型连接 = f"mc_假的{尾}"
        _c.execute(_t("""insert into model_connections
            (id, organization_id, project_id, purpose, adapter, display_name,
             status, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'路由','MockModelProvider', :n, 'active',
                    now(),'test', now(), 1)"""),
                   {"i": 真模型连接, "o": _org, "p": 项目,
                    "n": f"模型连接-给闸测用{尾}"})
        # ⚠️ **故意不给它探过的版本** —— 「没探过」那一道要撞得到
        _c.execute(_t("""insert into connection_versions
            (id, organization_id, project_id, connection_id, endpoint,
             secret_ref, capabilities, config_hash,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:cid,'https://x','keychain://x', null, :h,
                    now(),'test', now(), 1)"""),
                   {"i": f"cv_假的{尾}", "o": _org, "p": 项目,
                    "cid": 真模型连接, "h": 尾})

    基 = {"模式": "fixed_group", "没结果怎么办": "stop",
         "目录出错怎么办": "stop", "加载方式": "append_within_run",
         "限额": {"initial_candidates": 5, "new_definition_tokens": 4000,
                "active_definition_tokens": 12000, "max_rediscovery": 2,
                "selection_timeout_ms": 3000}}

    def 校(盖):
        _, r2 = 打("POST", f"{P}/tool-selection-policies/{pid}/validate",
                   dict(基, **盖))
        return " ".join(str(x) for x in ((r2 or {}).get("问题") or []))

    # ⚠️ 这两条**各自单独一次调用,每次只少一样** ——
    # 第一版把它们合在一次调用里(同时不给实验也不给连接),两条都过了,
    # 但那是「一次注入两个破坏」:**少的那一样是哪一个,断言分不出来**。
    文 = 校({"开独立路由": True, "路由模型连接": 真模型连接})
    ck("只少「路由实验」→ 点名要它(规格:只有实验证明有价值时才启用)",
       "必须指一次评测" in 文 and "必须给模型连接" not in 文, 文[:100])
    文 = 校({"开独立路由": True, "路由实验": 真实验})
    ck("只少「路由模型连接」→ 点名要它(规格 §9.6)",
       "必须给模型连接" in 文 and "必须指一次评测" not in 文, 文[:100])

    文 = 校({"开独立路由": True, "路由实验": "ev_不存在的",
           "路由模型连接": 真模型连接})
    ck("指一个不存在的实验 → 红", "路由实验 ev_不存在的 不存在" in 文, 文[:80])

    # ⚠️ **这一条必须传一条真的工具连接 id。**
    # 第一版传的是 `mc_不存在的`,而它过了 ——
    # 因为那句错误提示**永远带着**「不是工具连接」这几个字。
    # > 一条靠「提示文案里恰好有这几个字」成立的断言,
    # > 和一条真的验到了行为的断言,在绿勾上长得一模一样。
    文 = 校({"开独立路由": True, "路由实验": 真实验,
           "路由模型连接": 真工具连接})
    ck("**传一条真的工具连接 id 也红** —— 规格要的是模型连接,"
       "而后台这两张表只差一个词(闸的第一版就查错了表)",
       f"路由模型连接 {真工具连接} 不存在" in 文 and "不是工具连接" in 文, 文[:130])

    # 这条模型连接有版本但 capabilities 是空的 —— **没探过**
    文 = 校({"开独立路由": True, "路由实验": 真实验,
           "路由模型连接": 真模型连接})
    ck("模型连接存在、**但一个探过的版本都没有** → 红"
       "(不探就默认全支持,会在真跑时变成一个说不清的 400)",
       "一个探过的版本都没有" in 文, 文[:120])

    # 对照:把 capabilities 填上(= 探过了)→ 那一道该放行
    with _事务() as _c:
        _c.execute(_t("""update connection_versions
                         set capabilities = cast('{"max_tokens": true}' as jsonb)
                       where connection_id=:cid"""), {"cid": 真模型连接})
    文 = 校({"开独立路由": True, "路由实验": 真实验,
           "路由模型连接": 真模型连接})
    ck("**探过之后那一道放行** —— 对照:这道闸不是一律拒绝",
       "一个探过的版本都没有" not in 文, 文[:120])

    文 = 校({"开独立路由": False})
    ck("对照:不开路由时**不要求**实验和连接(这几道闸不是一律拒绝)",
       "必须指一次评测" not in 文 and "必须给模型连接" not in 文, 文[:80])

    清掉()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
