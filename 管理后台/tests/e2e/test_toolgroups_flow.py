#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具组五条接口 · **三道校验各防一件不同的事**。

## 这一份守的那句话

第三份规格 §3 的状态表后面紧跟一句:
**「本轮未加载」不等于「无权限」;「筛选得分高」不授予权限。**

所以**组只是一份搭配,不是一份授权** —— 一个 Agent 绑了某个组版本,
执行权仍要过 `tool_gateway` 的实时查验。这一份断那句话在接口上说出来了。

## 冻结时那三道校验,各防一件不同的事

| 校验 | 不拦的话会怎样 |
|---|---|
| **模型眼里同名** | 模型发出的调用分不清是哪一个 —— **而它看起来只是少了一个工具** |
| **配套关系成环** | 预算算法反复把两个都算进同一组,算出一个偏大的数,**把别的工具挤出去** |
| **成员版本还在不在** | 运行时**少给模型一个工具**,而人会去改提示词 |

⚠️ 「模型眼里同名」那一道 `agent_loop` **已经在补报**了,
而那段注释自己写着「**这在冻结版本时本该被拦住**」——
在运行时才发现的代价是:**那一轮的回答已经出去了**。

⚠️⚠️ 同名那一道**演示数据走不到**(两个工具名字不同)——
所以这一份**自己造一个同名的工具**。不造的话那条断言是空跑:
**空集合上所有性质都成立。**

⚠️ 前提 `make dev`。这一份自己造组和工具,跑完自己清。
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

同名工具 = f"td_同名{尾}"
同名版本 = f"tv_同名{尾}"


def 造一个同名工具():
    """造一个**和 `search` 在模型眼里同名**的工具版本。

    ⚠️ 不造的话「同名」那一道是空跑 —— 演示项目两个工具名字不同。
    **空集合上所有性质都成立。**
    模型看到的名字是 `tool_definitions.name`(见 `agent_loop` 里
    `名 = 契.get("name")`),所以同名 = 这一列相同。
    """
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        原名 = c.execute(text("""select name from tool_definitions
                              where project_id=:p and id in (
                                select tool_definition_id from tool_versions
                                 where project_id=:p and id='tv_search')"""),
                       {"p": 项目}).scalar()
        c.execute(text("""insert into tool_definitions
            (id, organization_id, project_id, name, purpose, side_effect_type,
             adapter, owner, status, draft_revision,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,'端到端造的同名工具','read_only',
                    'MockSearch','test','active',1, now(),'test', now(), 1)"""),
                  {"i": 同名工具, "o": org, "p": 项目, "n": 原名})
        c.execute(text("""insert into tool_versions
            (id, organization_id, project_id, tool_definition_id, version_no,
             model_description, input_schema, side_effect_type, content_hash,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:t,1,'同名的那个',
                    cast('{"type":"object","properties":{}}' as jsonb),
                    'read_only','h_同名',
                    now(),'test', now(), 1)"""),
                  {"i": 同名版本, "o": org, "p": 项目, "t": 同名工具})
    return 原名


def 清掉():
    """⚠️ **按名字删,不按 id 前缀。**

    第一版按 `tg_t{尾}%` 删 —— 而组的 id 是**服务端生成的**
    (`tg_` + 随机 hex),对不上那个前缀。
    > 一个按 id 前缀清理的收尾,在 id 由服务端生成时**什么都删不掉** ——
    > 而它不报错。

    发现它的方式:做「配套关系」那一页时接口报「在 5 个组里」,
    而真实的只有 1 个 —— 另外 4 个是历次测试的残留。
    (今天第五次撞「跑得起第二遍」和「不留垃圾」是两件事。)

    组名带 `尾` 所以认得出来。**先删版本再删组** —— 外键 RESTRICT。
    """
    with 事务() as c:
        c.execute(text("""delete from tool_group_versions where project_id=:p
                        and tool_group_id in (select id from tool_groups
                          where project_id=:p and name like :n)"""),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("delete from tool_groups where project_id=:p and name like :n"),
                  {"p": 项目, "n": f"%{尾}"})
        c.execute(text("delete from tool_versions where project_id=:p and id=:i"),
                  {"p": 项目, "i": 同名版本})
        c.execute(text("delete from tool_definitions where project_id=:p and id=:i"),
                  {"p": 项目, "i": 同名工具})


def main():
    print("\n\033[1m▸ 工具组 · 组只是搭配,不是授权\033[0m")

    print("\n▸ 一、建组:**说不出用途的组不许建**")
    码, 体 = 打("POST", f"{P}/tool-groups", {"名称": f"t{尾}"})
    ck("不写用途 → 422(一个说不出用途的组,"
       "下次没人知道该不该往里加工具)", 码 == 422, {"码": 码})
    码, 体 = 打("POST", f"{P}/tool-groups", {"用途": "没名字"})
    ck("不写名称 → 422", 码 == 422, {"码": 码})
    码, g = 打("POST", f"{P}/tool-groups",
             {"名称": f"端到端组{尾}", "用途": "验三道校验"})
    ck("建组 → 201", 码 == 201, {"码": 码})
    gid = (g or {}).get("id")
    ck("**明说「还没有版本」**(没有版本的组 Agent 引用不了 —— "
       "而「有组没版本」和「没有组」在 Agent 配置页上长得一样)",
       "没有版本" in str((g or {}).get("note") or ""),
       str((g or {}).get("note") or "")[:40])
    if not gid:
        print(f"\n❌ 过 {len(过)} / 挂 {len(挂)}(建不出组,**没往下跑**)")
        return 1

    print("\n▸ 二、组只是搭配,**不是授权**")
    码, 列 = 打("GET", f"{P}/tool-groups")
    ck("列表 200 且刚建的那个在里面", 码 == 200
       and any(x.get("id") == gid for x in ((列 or {}).get("items") or [])),
       (列 or {}).get("total"))
    # ⚠️ 这一条盯的是**那句话在不在**。规格 §3:「筛选得分高不授予权限」——
    # 而一个不说这句话的接口,会让人以为「绑了组就等于给了权限」。
    ck("**列表里明说「组不是授权」**(执行权仍要过工具网关)",
       "授权" in str((列 or {}).get("note") or "")
       and "网关" in str((列 or {}).get("note") or ""),
       str((列 or {}).get("note") or "")[:50])

    print("\n▸ 三、三道校验:**各防一件不同的事**")
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions", {"成员": []})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("空组 → 422(一个空组绑上去,表现是「Agent 什么工具都没有」,"
       "而人会去改提示词)",
       码 == 422 and any("一个成员都没有" in x for x in 闸), {"码": 码})
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": [f"tv_不存在{尾}"]})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("成员版本不在 → 422(运行时的表现是**少给模型一个工具**,"
       "而人会去改提示词)",
       码 == 422 and any("不在了" in x for x in 闸), {"码": 码, "闸": 闸[:1]})
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search", "tv_search"]})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("同一个版本列两次 → 422(**预算会把它算两遍**)",
       码 == 422 and any("两次" in x for x in 闸), {"码": 码})
    # ⚠️ **配套成环。** 两边都在组里 —— 否则会先被「指向组外」那条拦住,
    # 而那时这一条**什么都没验到**。
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search", "tv_write_report"],
              "配套关系": {"tv_search": ["tv_write_report"],
                      "tv_write_report": ["tv_search"]}})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    环句 = next((x for x in 闸 if "成环" in x), "")
    ck("配套成环 → 422(预算算法反复把两个都算进同一组,"
       "**算出一个偏大的数,然后把别的工具挤出去**)",
       码 == 422 and bool(环句), {"码": 码})
    # ⚠️ 这一条盯的是**路径打对了**。第一版多打一个节点(`a → b → a → a`),
    # 而**一条自己都打不对的路径,读的人不会相信它**。
    ck("而且**环的路径首尾是同一个、不重复**"
       "(第一版多打了一个节点 —— 一条自己都打不对的路径,人不会相信它)",
       环句.count("tv_search") == 2 and "→ tv_search → tv_search" not in 环句,
       环句[:70])
    # ⚠️ 这一条是「集合运算优先级」那个 bug 的回归测试。
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search", "tv_write_report"],
              "配套关系": {"tv_write_report": ["tv_search"]}})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("**组内成员不许被报成「指向组外」**"
       "(Python 的 `|` 优先级高于 `-`,少个括号就会把组内的报成组外 —— "
       "CLAUDE.md 里记着这条)",
       not any("不是这一组的成员" in x for x in 闸), 闸[:1] or "没误报")
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search"], "配套关系": {"tv_search": ["tv_write_report"]}})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("配套指向**组外**的 → 422(指向组外的配套在加载时拿不到,"
       "而「配套不全」和「没配套」在模型那边长得一样)",
       码 == 422 and any("不是这一组的成员" in x for x in 闸), {"码": 码})

    print("\n▸ 四、**模型眼里同名** —— 这一道演示数据走不到,自己造")
    原名 = 造一个同名工具()
    ck(f"造了一个和 `{原名}` 同名的工具版本"
       "(**不造的话下面那条是空跑** —— 空集合上所有性质都成立)",
       bool(原名), {"同名的 name": 原名})
    码, 体 = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search", 同名版本]})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck("两个在模型眼里同名的成员 → 422(模型发出的调用分不清是哪一个,"
       "**而它看起来只是少了一个工具**)",
       码 == 422 and any("同名" in x for x in 闸), {"码": 码, "闸": 闸[:1]})
    ck("而且理由里**点名那个名字**(只说「有同名的」要人自己去找)",
       any(原名 in x for x in 闸), [x[:60] for x in 闸 if "同名" in x])
    ck("**还说了「运行时也会报,但那时回答已经出去了」**"
       "(说清为什么要在冻结时拦)",
       any("已经出去" in x for x in 闸), [x[-40:] for x in 闸 if "同名" in x])

    print("\n▸ 五、正常冻结 + 乐观锁")
    码, v = 打("POST", f"{P}/tool-groups/{gid}/versions",
             {"成员": ["tv_search",
                     {"tool_version_id": "tv_write_report", "必不可少吗": True}],
              "配套关系": {"tv_write_report": ["tv_search"]},
              "变更说明": "首版:先搜后写"})
    ck("三道都过 → 201", 码 == 201, {"码": 码})
    ck("**分得出「这一组里有它」和「这一轮必须给它」**"
       "(A-5 的预算先放必需的)",
       (v or {}).get("成员数") == 2 and (v or {}).get("必不可少的") == 1,
       {"成员数": (v or {}).get("成员数"), "必不可少的": (v or {}).get("必不可少的")})
    ck("**明说了「组不是授权」**(冻结成功之后尤其要说 —— "
       "那一刻最容易被读成「给了权限」)",
       "授权" in str((v or {}).get("note") or ""),
       str((v or {}).get("note") or "")[-40:])
    ck("**说清了三道校验为什么在冻结时做**(版本不可变 —— "
       "冻结之后再发现只能出新版本,而旧那版可能已经被引用了)",
       "不可变" in str((v or {}).get("⚠️三道校验为什么在冻结时做") or ""),
       str((v or {}).get("⚠️三道校验为什么在冻结时做") or "")[:40])
    码, det = 打("GET", f"{P}/tool-groups/{gid}")
    ck("详情里版本历史有那一版,而且带成员和配套",
       码 == 200 and ((det or {}).get("版本历史") or [])
       and ((det or {}).get("版本历史") or [])[0].get("成员数") == 2,
       {"版本数": len((det or {}).get("版本历史") or [])})
    码, 体 = 打("PATCH", f"{P}/tool-groups/{gid}/draft", {"用途": "改一下"})
    ck("改草稿不带 If-Match → 409 IF_MATCH_REQUIRED",
       码 == 409 and (体 or {}).get("code") == "IF_MATCH_REQUIRED", {"码": 码})
    rev = (det or {}).get("draft_revision")
    码, 体 = 打("PATCH", f"{P}/tool-groups/{gid}/draft", {"用途": "改好了"},
             头={"If-Match": str(rev)})
    ck("带对的 If-Match → 200,而且 draft_revision 涨了",
       码 == 200 and (体 or {}).get("draft_revision") == (rev or 0) + 1,
       {"码": 码, "前": rev, "后": (体 or {}).get("draft_revision")})
    码, 体 = 打("PATCH", f"{P}/tool-groups/{gid}/draft", {"用途": "再改"},
             头={"If-Match": str(rev)})
    ck("拿旧 revision 再改 → 409(**乐观锁真的在拦**)", 码 == 409, {"码": 码})
    # ⚠️ **改草稿不许动已冻结的版本。**
    码, det2 = 打("GET", f"{P}/tool-groups/{gid}")
    ck("改完草稿,**已冻结那一版一个字没动**",
       ((det2 or {}).get("版本历史") or [{}])[0].get("内容哈希")
       == ((det or {}).get("版本历史") or [{}])[0].get("内容哈希"),
       ((det2 or {}).get("版本历史") or [{}])[0].get("内容哈希"))
    码, 体 = 打("POST", f"{P}/tool-groups", {"名称": "viewer 建的", "用途": "x"},
             谁="U003")
    ck("viewer 建组 → 403(要「改编排草稿」这条能力)", 码 == 403, {"码": 码})

    清掉()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
